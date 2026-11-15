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
import { WilcoMascot } from "@/components/brand";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ChatMarkdown } from "@/components/chat-markdown";
import {
  MemorySourceRail,
  memorySourceKey,
} from "@/components/memory-source-rail";
import { CitedMarkdown, ResolvedCitation } from "@/components/cited-markdown";
import { ChatActions } from "@/components/chat-actions";
import { VoiceAskButton } from "@/components/voice-ask-button";
import {
  History,
  ArrowUpRight,
  CalendarDays,
  ChevronDown,
  ExternalLink,
  FileSearch,
  MessagesSquare,
  Plus,
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

function messageTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function MemoryPage() {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [conversations, setConversations] = useState<
    MemoryConversationSummary[]
  >([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sourceSelection, setSourceSelection] = useState<{
    key: string;
    seq?: number;
  } | null>(null);
  const [inspectedSources, setInspectedSources] = useState<ChatSource[] | null>(
    null,
  );
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(
    null,
  );
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [meetingSearch, setMeetingSearch] = useState("");
  // An explicit set of meetings to ask across. Empty means all company memory.
  const [scope, setScope] = useState<MeetingSummary[]>([]);
  const scopedMeeting = scope.length === 1 ? scope[0] : null;
  const router = useRouter();
  const [scopeOpen, setScopeOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [draftScope, setDraftScope] = useState<MeetingSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [meetingsError, setMeetingsError] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scopeLabel = scopedMeeting
    ? scopedMeeting.title
    : scope.length
      ? `${scope.length} meetings`
      : meetings.length
        ? `${meetings.length} meetings`
        : "All meetings";
  const active = entries.length > 0;

  useEffect(() => {
    api
      .listMeetings()
      .then(setMeetings)
      .catch(() => setMeetingsError(true));
    refreshConversations();
  }, []);

  function refreshConversations() {
    setHistoryLoading(true);
    setHistoryError(false);
    api
      .listMemoryConversations()
      .then(setConversations)
      .catch(() => setHistoryError(true))
      .finally(() => setHistoryLoading(false));
  }

  const stick = useStickToBottom();

  const visibleMeetings = useMemo(() => {
    const search = meetingSearch.trim().toLocaleLowerCase();
    return meetings
      .filter(
        (meeting) =>
          !search || meeting.title.toLocaleLowerCase().includes(search),
      )
      .slice(0, 12);
  }, [meetingSearch, meetings]);

  function startNewChat(nextScope: MeetingSummary[] = scope) {
    setActiveId(null);
    setScope(nextScope);
    setEntries([]);
    setInspectedSources(null);
    setSourceSelection(null);
    setQuery("");
    setError(null);
    setLastFailedQuestion(null);
  }

  function chooseScope(meeting: MeetingSummary | null) {
    const draft = query;
    startNewChat(meeting ? [meeting] : []);
    setQuery(draft);
  }

  function toggleDraft(meeting: MeetingSummary) {
    setDraftScope((current) =>
      current.some((item) => item.id === meeting.id)
        ? current.filter((item) => item.id !== meeting.id)
        : current.length < MAX_SCOPE
          ? [...current, meeting]
          : current,
    );
  }

  function openCitation(citation: ResolvedCitation) {
    const key = memorySourceKey(citation.source);
    setSourceSelection({ key, seq: citation.segment?.seq });
    requestAnimationFrame(() =>
      document
        .getElementById(`memory-source-${key}`)
        ?.scrollIntoView({
          block: "nearest",
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
        }),
    );
  }

  async function openConversation(conversation: MemoryConversationSummary) {
    if (busy || opening) return;
    setOpening(true);
    setError(null);
    setLastFailedQuestion(null);
    try {
      const detail = await api.getMemoryConversation(conversation.id);
      setActiveId(conversation.id);
      setHistoryOpen(false);
      setEntries(
        detail.messages.map((message) => ({
          role: message.role,
          content: message.content,
          sources: message.sources ?? undefined,
          createdAt: message.created_at,
        })),
      );
      const ids = detail.scope_meeting_ids?.length
        ? detail.scope_meeting_ids
        : detail.meeting_id
          ? [detail.meeting_id]
          : [];
      setScope(meetings.filter((meeting) => ids.includes(meeting.id)));
    } catch {
      setError("This conversation could not be loaded. Try again.");
    } finally {
      setOpening(false);
    }
  }

  async function deleteConversation(id: string) {
    if (pendingDelete !== id) {
      setPendingDelete(id);
      return;
    }
    setOpening(true);
    try {
      await api.deleteMemoryConversation(id);
      if (activeId === id) startNewChat([]);
      setPendingDelete(null);
      refreshConversations();
    } catch {
      setError("Chat couldn’t be deleted. Try again.");
    } finally {
      setOpening(false);
    }
  }

  async function ask(question: string, spoken = false) {
    if (!question || busy || opening) return;
    stick.pin();
    setInspectedSources(null);
    setSourceSelection(null);
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
          : "Company Memory could not answer. Check the connection and try again.",
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

  const sourcePicker = (
    <Dialog
      open={scopeOpen}
      onOpenChange={(open) => {
        setScopeOpen(open);
        if (open) {
          setDraftScope(scope);
          setMeetingSearch("");
        }
      }}
    >
      <DialogTrigger
        render={<Button variant="ghost" size="sm" disabled={busy || opening} />}
      >
        <FileSearch aria-hidden="true" />
        <span className="truncate">{scopeLabel}</span>
        <ChevronDown aria-hidden="true" />
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogTitle>Choose meetings</DialogTitle>
        <DialogDescription>
          Pick up to 10 meetings. Changing sources starts a new chat.
        </DialogDescription>
        <Input
          aria-label="Find a meeting"
          placeholder="Find a meeting…"
          value={meetingSearch}
          onChange={(event) => setMeetingSearch(event.target.value)}
        />
        <Button
          variant={draftScope.length ? "outline" : "secondary"}
          onClick={() => setDraftScope([])}
        >
          All my meetings{" "}
          {draftScope.length === 0 && <Check aria-hidden="true" />}
        </Button>
        <div className="memory-picker-list">
          {meetingsError && (
            <p role="alert">
              Meetings couldn’t load. Reload this page to try again.
            </p>
          )}
          {!meetingsError && visibleMeetings.length === 0 && (
            <p>No meetings found.</p>
          )}
          {visibleMeetings.map((meeting) => {
            const selected = draftScope.some((item) => item.id === meeting.id);
            return (
              <label key={meeting.id} className="memory-picker-row">
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={!selected && draftScope.length >= MAX_SCOPE}
                  onChange={() => toggleDraft(meeting)}
                />
                <span>
                  <strong>{meeting.title}</strong>
                  <small>{new Date(meeting.date).toLocaleDateString()}</small>
                </span>
              </label>
            );
          })}
        </div>
        <div className="memory-picker-footer">
          <span>
            {draftScope.length
              ? `${draftScope.length} of 10 selected`
              : "Search all meetings you can access"}
          </span>
          <Button
            onClick={() => {
              const changed =
                scope
                  .map((x) => x.id)
                  .sort()
                  .join() !==
                draftScope
                  .map((x) => x.id)
                  .sort()
                  .join();
              if (changed) {
                const draft = query;
                startNewChat(draftScope);
                setQuery(draft);
              }
              setScopeOpen(false);
            }}
          >
            Apply
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
  const latestSources =
    inspectedSources ??
    [...entries]
      .reverse()
      .find((entry) => entry.role === "assistant" && entry.sources?.length)
      ?.sources ??
    [];
  const composer = (
    <div className="memory-compose-wrap">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(query.trim());
        }}
        className="memory-composer"
        aria-label="Ask your meetings"
      >
        <Textarea
          ref={inputRef}
          aria-label="Question about your meetings"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void ask(query.trim());
            }
          }}
          placeholder={
            scopedMeeting
              ? `Ask about “${scopedMeeting.title}”…`
              : scope.length > 1
                ? "Ask across the selected meetings…"
                : "Ask anything from your meetings…"
          }
          rows={2}
          className="min-h-16 resize-none border-0 bg-transparent dark:bg-transparent px-3 py-2 shadow-none focus-visible:ring-0"
        />
        <VoiceAskButton
          disabled={busy || opening}
          onQuestion={(text) => void ask(text, true)}
          onError={setError}
        />
        <Button
          type="submit"
          size="icon"
          disabled={busy || opening || !query.trim()}
          aria-label="Send question"
          className="h-10 w-10 shrink-0 rounded-xl"
        >
          <Send className="h-4 w-4" />
        </Button>
      </form>
      <div className="memory-compose-meta"></div>
    </div>
  );

  return (
    <div className="memory-studio engagement-memory" data-active={active}>
      <div className="memory-toolbar">
        {sourcePicker}
        <div>
          <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
            <DialogTrigger
              render={
                <Button variant="ghost" size="sm" disabled={busy || opening} />
              }
            >
              <History aria-hidden="true" />
              History
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
              <DialogTitle>Recent chats</DialogTitle>
              <DialogDescription>
                Continue where you left off.
              </DialogDescription>
              <div className="memory-history-list">
                {historyLoading ? (
                  <p role="status">Loading chats…</p>
                ) : historyError ? (
                  <div role="alert">
                    <p>Chats couldn’t load.</p>
                    <Button variant="outline" onClick={refreshConversations}>
                      Try again
                    </Button>
                  </div>
                ) : conversations.length === 0 ? (
                  <p>Your chats will appear here after your first question.</p>
                ) : (
                  conversations.map((conversation) => (
                    <div className="memory-history-row" key={conversation.id}>
                      <button
                        type="button"
                        disabled={opening}
                        onClick={() => void openConversation(conversation)}
                      >
                        <MessagesSquare aria-hidden="true" />
                        <span>{conversation.title}</span>
                        <ArrowUpRight aria-hidden="true" />
                      </button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={opening}
                        onClick={() => void deleteConversation(conversation.id)}
                        aria-label={`${pendingDelete === conversation.id ? "Confirm deletion of" : "Delete"} ${conversation.title}`}
                      >
                        {pendingDelete === conversation.id ? (
                          "Delete chat?"
                        ) : (
                          <Trash2 aria-hidden="true" />
                        )}
                      </Button>
                      {pendingDelete === conversation.id && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPendingDelete(null)}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  ))
                )}
              </div>
              {error && <p role="alert">{error}</p>}
            </DialogContent>
          </Dialog>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || opening}
            onClick={() => {
              startNewChat();
              inputRef.current?.focus();
            }}
          >
            <Plus aria-hidden="true" />
            New chat
          </Button>
        </div>
      </div>
      <div className="memory-work-columns">
        {!active ? (
          <div className="memory-start">
            <div className="memory-intro">
              <div>
                <h1 className="two-tone">
                  It’s in your meetings.<span>Let’s find it.</span>
                </h1>
              </div>
              <WilcoMascot className="memory-mascot" />
            </div>
            {composer}
            <div className="memory-prompts" aria-label="Start with a question">
              {[
                [
                  "Release decisions",
                  "What changed in the latest release plan?",
                ],
                ["Open blockers", "Which launch blockers are still open?"],
                [
                  "My follow-ups",
                  "What engineering work should I follow up on this week?",
                ],
              ].map(([label, question]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => {
                    void ask(question);
                  }}
                >
                  {label}
                  <ArrowUpRight aria-hidden="true" />
                </button>
              ))}
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <section className="memory-recent" aria-label="Recent meetings">
              <header>
                <h2>Start from a meeting</h2>
                <Link href="/meetings">View all</Link>
              </header>
              {meetingsError ? (
                <p>Meetings couldn’t load.</p>
              ) : meetings.length === 0 ? (
                <p>Your recorded meetings will appear here.</p>
              ) : (
                meetings.slice(0, 3).map((meeting) => (
                  <button
                    type="button"
                    key={meeting.id}
                    onClick={() => {
                      chooseScope(meeting);
                      inputRef.current?.focus();
                    }}
                    aria-label={`Ask about ${meeting.title}`}
                  >
                    <span className="memory-meeting-icon">
                      <Video aria-hidden="true" />
                    </span>
                    <span>
                      <strong>{meeting.title}</strong>
                      <small>
                        {new Date(meeting.date).toLocaleDateString(undefined, {
                          day: "numeric",
                          month: "short",
                        })}
                        {meeting.duration_minutes
                          ? ` · ${meeting.duration_minutes} min`
                          : ""}
                      </small>
                    </span>
                    <ArrowUpRight aria-hidden="true" />
                  </button>
                ))
              )}
            </section>
          </div>
        ) : (
          <section className="memory-conversation" aria-label="Conversation">
            <h1 className="sr-only">Ask Wilco</h1>
            <div ref={stick.panelRef} className="memory-messages">
              <div className="memory-message-column">
                {entries.map((entry, index) =>
                  entry.role === "user" ? (
                    <div
                      key={index}
                      className="flex max-w-[82%] flex-col items-end self-end"
                    >
                      <div className="memory-user-bubble rounded-[20px] rounded-br-md bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground shadow-sm">
                        <p className="whitespace-pre-wrap">{entry.content}</p>
                      </div>
                      <span className="mt-1.5 pr-1 text-[10px] text-muted-foreground">
                        You · {messageTime(entry.createdAt)}
                      </span>
                    </div>
                  ) : (
                    <div
                      key={index}
                      className="flex max-w-[94%] items-start gap-3 self-start"
                    >
                      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent text-foreground">
                        <Sparkles className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="mb-1.5 flex items-center gap-2">
                          <span className="text-xs font-semibold text-foreground">
                            Wilco
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {messageTime(entry.createdAt)}
                          </span>
                        </div>
                        <div className="memory-answer rounded-[20px] rounded-tl-md border bg-card px-4 py-4 leading-6 shadow-[0_10px_28px_-24px_rgba(15,45,38,0.7)] sm:px-5">
                          {entry.sources?.some((source) => source.tag) ? (
                            <CitedMarkdown
                              numbers
                              content={entry.content}
                              sources={entry.sources}
                              onCite={(citation) => {
                                setInspectedSources(entry.sources ?? []);
                                openCitation(citation);
                              }}
                            />
                          ) : (
                            <ChatMarkdown content={entry.content} />
                          )}
                        </div>
                        <ChatActions
                          content={entry.content}
                          onRetry={() => {
                            if (!busy) retryAnswer(index);
                          }}
                          speak={entry.spoken}
                        />
                      </div>
                    </div>
                  ),
                )}

                {busy && (
                  <div
                    role="status"
                    className="flex items-center gap-3 self-start"
                  >
                    <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent text-foreground">
                      <Sparkles className="h-3.5 w-3.5 animate-pulse" />
                    </span>
                    <div className="rounded-2xl rounded-tl-md border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm">
                      Searching your meetings
                      <span className="animate-pulse">…</span>
                    </div>
                  </div>
                )}

                {error && (
                  <div
                    role="alert"
                    className="flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
                  >
                    <span>{error}</span>
                    {lastFailedQuestion && (
                      <button
                        type="button"
                        className="shrink-0 font-semibold underline"
                        onClick={() => ask(lastFailedQuestion)}
                      >
                        Try again
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
            {composer}
          </section>
        )}
        <MemorySourceRail
          sources={latestSources}
          meetings={meetings}
          selected={sourceSelection}
          onSelect={(source) => {
            if (!latestSources.length) {
              const meeting = meetings.find(
                (row) => row.id === source.meeting_id,
              );
              if (meeting) chooseScope(meeting);
            }
            setSourceSelection({
              key: memorySourceKey(source),
              seq: source.segments?.[0]?.seq,
            });
          }}
          onAsk={(question) => void ask(question)}
          busy={busy || opening}
        />
      </div>
    </div>
  );
}
