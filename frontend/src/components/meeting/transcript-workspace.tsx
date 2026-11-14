"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  MeetingAttendee,
  MeetingBookmarkItem,
  MeetingCommentItem,
  TranscriptEditEntry,
  TranscriptExportFormat,
  TranscriptPage,
  TranscriptSegment,
} from "@/lib/api";
import { downloadBlob, formatClock } from "@/lib/media-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AudioLines,
  Bookmark,
  Check,
  History,
  ListRestart,
  MessageSquare,
  Pencil,
  Play,
  Scissors,
  Search,
  Trash2,
  Undo2,
  UserPen,
  X,
} from "lucide-react";

const PAGE_SIZE = 500;
const LOW_CONFIDENCE = 0.6;

export interface TranscriptFocus {
  segmentId: string;
  nonce: number;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function Highlighted({ text, query }: { text: string; query: string }) {
  if (!query.trim()) return <>{text}</>;
  const parts = text.split(new RegExp(`(${escapeRegExp(query.trim())})`, "gi"));
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="rounded-sm bg-warning/70 px-0.5 text-foreground">{part}</mark>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        ),
      )}
    </>
  );
}

/** Each word's [start, end] in ms: the recorded word timings when they still
 * match the text word for word, else spread across the line by word length
 * (older meetings, corrected lines). */
export function wordTimings(text: string, startMs: number, endMs: number | null, recorded?: [number, number][] | null): [number, number][] {
  const words = text.split(/\s+/).filter(Boolean);
  if (recorded && recorded.length === words.length) return recorded;
  const end = endMs !== null && endMs > startMs ? endMs : startMs + words.length * 350;
  const total = words.reduce((sum, word) => sum + word.length + 1, 0) || 1;
  let cursor = 0;
  return words.map((word) => {
    const from = startMs + ((end - startMs) * cursor) / total;
    cursor += word.length + 1;
    return [Math.round(from), Math.round(startMs + ((end - startMs) * cursor) / total)];
  });
}

/** The line being played, lit word by word like synced lyrics. Reads the
 * audio clock every animation frame but re-renders only when the spoken
 * word changes, so a long transcript isn't redrawn 60 times a second. */
function KaraokeText({
  text,
  startMs,
  endMs,
  recorded,
  getPlaybackMs,
}: {
  text: string;
  startMs: number;
  endMs: number | null;
  recorded?: [number, number][] | null;
  getPlaybackMs: () => number | null;
}) {
  const parts = useMemo(() => text.split(/(\s+)/), [text]);
  const times = useMemo(() => wordTimings(text, startMs, endMs, recorded), [text, startMs, endMs, recorded]);
  const [spoken, setSpoken] = useState(-1);

  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const now = getPlaybackMs();
      if (now !== null) {
        let index = -1;
        while (index + 1 < times.length && times[index + 1][0] <= now) index += 1;
        setSpoken((previous) => (previous === index ? previous : index));
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [times, getPlaybackMs]);

  let wordIndex = -1;
  return (
    <>
      {parts.map((part, i) => {
        if (!part.trim()) return <Fragment key={i}>{part}</Fragment>;
        wordIndex += 1;
        const state = wordIndex < spoken ? "said" : wordIndex === spoken ? "now" : "next";
        return (
          <span
            key={i}
            className={`transition-colors duration-150 ${
              state === "next" ? "text-foreground/35" : state === "now" ? "text-primary" : "text-foreground"
            }`}
          >
            {part}
          </span>
        );
      })}
    </>
  );
}

export function TranscriptWorkspace({
  meetingId,
  attendees,
  currentMs,
  playing = false,
  getPlaybackMs,
  canPlay,
  focus,
  onSeek,
  onPlayRange,
  onTranscriptChanged,
}: {
  meetingId: string;
  attendees: MeetingAttendee[];
  currentMs: number | null;
  /** The recording is playing (not paused): show the lyrics view. */
  playing?: boolean;
  /** The audio clock, read every frame for word-by-word highlighting. */
  getPlaybackMs?: () => number | null;
  canPlay: boolean;
  focus: TranscriptFocus | null;
  onSeek: (ms: number) => void;
  onPlayRange: (startMs: number, endMs: number | null) => void;
  onTranscriptChanged: () => void;
}) {
  const [page, setPage] = useState<TranscriptPage | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [speaker, setSpeaker] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [commentingOn, setCommentingOn] = useState<string | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [meetingCommentDraft, setMeetingCommentDraft] = useState("");
  const [comments, setComments] = useState<MeetingCommentItem[]>([]);
  const [bookmarks, setBookmarks] = useState<MeetingBookmarkItem[]>([]);
  const [bookmarkLabel, setBookmarkLabel] = useState("");
  const [renameOpen, setRenameOpen] = useState(false);
  const [speakerDraft, setSpeakerDraft] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<TranscriptEditEntry[] | null>(null);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [flashId, setFlashId] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const listRef = useRef<HTMLDivElement | null>(null);
  const pendingFocus = useRef<string | null>(null);

  const load = useCallback(
    async (opts: { offset?: number; q?: string; speaker?: string | null; limit?: number } = {}) => {
      setLoading(true);
      setError(null);
      try {
        const result = await api.getTranscript(meetingId, {
          q: opts.q ?? appliedQuery,
          speaker: (opts.speaker === undefined ? speaker : opts.speaker) ?? undefined,
          offset: opts.offset ?? 0,
          limit: opts.limit ?? PAGE_SIZE,
        });
        setPage(result);
        setSegments((current) => (opts.offset ? [...current, ...result.segments] : result.segments));
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "The transcript could not be loaded");
      } finally {
        setLoading(false);
      }
    },
    [meetingId, appliedQuery, speaker],
  );

  const loadSide = useCallback(async () => {
    const [nextComments, nextBookmarks] = await Promise.all([
      api.listMeetingComments(meetingId).catch(() => []),
      api.listMeetingBookmarks(meetingId).catch(() => []),
    ]);
    setComments(nextComments);
    setBookmarks(nextBookmarks);
  }, [meetingId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadSide();
  }, [loadSide]);

  useEffect(() => {
    const handle = window.setTimeout(() => setAppliedQuery(query.trim()), 250);
    return () => window.clearTimeout(handle);
  }, [query]);

  // A citation or evidence chip elsewhere asked to show one line. If it is
  // hidden by a filter or not paged in yet, clear filters and load it all.
  useEffect(() => {
    if (!focus) return;
    pendingFocus.current = focus.segmentId;
    if (!segments.some((segment) => segment.id === focus.segmentId)) {
      setQuery("");
      setAppliedQuery("");
      setSpeaker(null);
      void load({ q: "", speaker: null, limit: 2000 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  useEffect(() => {
    const target = pendingFocus.current;
    if (!target) return;
    const row = rowRefs.current.get(target);
    if (!row) return;
    pendingFocus.current = null;
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    setFlashId(target);
    const handle = window.setTimeout(() => setFlashId(null), 2000);
    return () => window.clearTimeout(handle);
  }, [segments, focus]);

  const activeId = useMemo(() => {
    if (currentMs === null) return null;
    let active: TranscriptSegment | null = null;
    for (const segment of segments) {
      if (segment.start_ms === null) continue;
      if (segment.start_ms > currentMs) break;
      active = segment;
    }
    if (!active) return null;
    // While it plays, a pause in the conversation keeps the last line lit
    // until the next one starts, like synced lyrics.
    if (!playing && active.end_ms !== null && currentMs > active.end_ms + 1500) return null;
    return active.id;
  }, [segments, currentMs, playing]);

  // Keep the line being played centred in the transcript box (the box
  // scrolls, not the page), the way synced lyrics do.
  const centre = useCallback((id: string, behavior: ScrollBehavior = "smooth") => {
    const list = listRef.current;
    const row = rowRefs.current.get(id);
    if (!list || !row) return;
    list.scrollTo({ top: row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2, behavior });
  }, []);

  useEffect(() => {
    if (!follow || !activeId || editing) return;
    centre(activeId);
  }, [activeId, follow, editing, centre]);

  // Scrolling by hand while it plays means "let me look around": stop
  // following until "Back to now playing".
  const detach = useCallback(() => {
    if (playing && follow) setFollow(false);
  }, [playing, follow]);
  const lyrics = playing && follow && !appliedQuery && speaker === null;

  const commentsBySegment = useMemo(() => {
    const map = new Map<string, MeetingCommentItem[]>();
    for (const comment of comments) {
      if (!comment.segment_id) continue;
      map.set(comment.segment_id, [...(map.get(comment.segment_id) ?? []), comment]);
    }
    return map;
  }, [comments]);

  function applyEdit(updated: TranscriptSegment) {
    setSegments((current) => current.map((segment) => (segment.id === updated.id ? { ...segment, ...updated } : segment)));
    onTranscriptChanged();
  }

  async function saveEdit(segment: TranscriptSegment) {
    const text = draft.trim();
    if (!text || text === segment.text) {
      setEditing(null);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      applyEdit(await api.editTranscriptSegment(meetingId, segment.id, text));
      setEditing(null);
      setHistory(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The correction could not be saved");
    } finally {
      setSaving(false);
    }
  }

  async function revert(segment: TranscriptSegment) {
    setSaving(true);
    try {
      applyEdit(await api.revertTranscriptSegment(meetingId, segment.id));
      setHistory(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The line could not be restored");
    } finally {
      setSaving(false);
    }
  }

  async function addComment(segmentId: string | null) {
    const body = (segmentId ? commentDraft : meetingCommentDraft).trim();
    if (!body) return;
    try {
      const comment = await api.addMeetingComment(meetingId, body, segmentId);
      setComments((current) => [...current, comment]);
      if (segmentId) {
        setCommentDraft("");
        setCommentingOn(null);
      } else {
        setMeetingCommentDraft("");
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The comment could not be added");
    }
  }

  async function removeComment(id: string) {
    try {
      await api.deleteMeetingComment(meetingId, id);
      setComments((current) => current.filter((comment) => comment.id !== id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The comment could not be deleted");
    }
  }

  async function clip(segment: TranscriptSegment) {
    try {
      const bookmark = await api.addMeetingBookmark(meetingId, {
        label: `${segment.speaker}: ${segment.text.slice(0, 60)}${segment.text.length > 60 ? "…" : ""}`,
        segment_id: segment.id,
      });
      setBookmarks((current) => [...current, bookmark].sort((a, b) => (a.start_ms ?? Infinity) - (b.start_ms ?? Infinity)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The clip could not be saved");
    }
  }

  async function bookmarkNow() {
    if (currentMs === null) return;
    try {
      const bookmark = await api.addMeetingBookmark(meetingId, {
        label: bookmarkLabel.trim() || `Moment at ${formatClock(currentMs)}`,
        start_ms: Math.round(currentMs),
      });
      setBookmarks((current) => [...current, bookmark].sort((a, b) => (a.start_ms ?? Infinity) - (b.start_ms ?? Infinity)));
      setBookmarkLabel("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The bookmark could not be saved");
    }
  }

  async function removeBookmark(id: string) {
    try {
      await api.deleteMeetingBookmark(meetingId, id);
      setBookmarks((current) => current.filter((bookmark) => bookmark.id !== id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The bookmark could not be deleted");
    }
  }

  async function saveSpeakers() {
    if (!page) return;
    const changes: Record<string, string> = {};
    for (const entry of page.speakers) {
      const next = (speakerDraft[entry.key] ?? "").trim();
      const current = entry.named ? entry.label : "";
      if (next !== current) changes[entry.key] = next;
    }
    setSaving(true);
    try {
      if (Object.keys(changes).length) {
        await api.renameTranscriptSpeakers(meetingId, changes);
        await load();
        setHistory(null);
        onTranscriptChanged();
      }
      setRenameOpen(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Speaker names could not be saved");
    } finally {
      setSaving(false);
    }
  }

  async function exportAs(format: TranscriptExportFormat) {
    setError(null);
    try {
      const blob = await api.exportTranscript(meetingId, format);
      downloadBlob(blob, `transcript.${format}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Export failed");
    }
  }

  async function switchToRecording() {
    setSaving(true);
    try {
      await api.useRecordingTranscript(meetingId);
      setSwitchOpen(false);
      await load({ q: "", speaker: null });
      setHistory(null);
      onTranscriptChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not switch transcripts");
    } finally {
      setSaving(false);
    }
  }

  function openRename() {
    if (!page) return;
    setSpeakerDraft(Object.fromEntries(page.speakers.map((entry) => [entry.key, entry.named ? entry.label : ""])));
    setRenameOpen(true);
  }

  if (!page && loading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2, 3].map((index) => <Skeleton key={index} className="h-14 w-full" />)}
      </div>
    );
  }

  if (page && page.total === 0) {
    return <p className="text-sm text-muted-foreground">No transcript yet. It appears here once transcription finishes.</p>;
  }

  const hasMore = page ? page.offset + segments.length < page.matched && segments.length < page.matched : false;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search className="absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search the transcript"
              aria-label="Search the transcript"
              className="pl-8"
            />
          </div>
          <Button variant="outline" size="sm" onClick={openRename} disabled={!page}>
            <UserPen className="h-3.5 w-3.5" /> Name speakers
          </Button>
          <select
            aria-label="Export transcript"
            className="h-8 w-32 shrink-0 rounded-md border bg-background px-2 text-sm"
            value=""
            onChange={(event) => {
              const format = event.target.value as TranscriptExportFormat;
              event.target.value = "";
              if (format) void exportAs(format);
            }}
          >
            <option value="">Export…</option>
            <option value="txt">Plain text (.txt)</option>
            <option value="md">Markdown (.md)</option>
            <option value="json">JSON (.json)</option>
            <option value="srt" disabled={!page?.has_timestamps}>Subtitles (.srt){page?.has_timestamps ? "" : " — needs timestamps"}</option>
            <option value="vtt" disabled={!page?.has_timestamps}>WebVTT (.vtt){page?.has_timestamps ? "" : " — needs timestamps"}</option>
          </select>
          {canPlay && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} />
              Follow playback
            </label>
          )}
        </div>

        {page && page.speakers.length > 1 && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by speaker">
            <button
              type="button"
              onClick={() => setSpeaker(null)}
              aria-pressed={speaker === null}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${speaker === null ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            >
              Everyone
            </button>
            {page.speakers.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() => setSpeaker(speaker === entry.key ? null : entry.key)}
                aria-pressed={speaker === entry.key}
                className={`rounded-full border px-2.5 py-0.5 text-xs ${speaker === entry.key ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"}`}
              >
                {entry.label} <span className="opacity-70">· {entry.segment_count}</span>
              </button>
            ))}
          </div>
        )}

        {page && (
          <p className="text-xs text-muted-foreground">
            {appliedQuery || speaker !== null ? `${page.matched} of ${page.total} lines match` : `${page.total} lines`}
            {!page.has_timestamps && " · no timestamps in this transcript"}
            {!page.speakers.some((entry) => entry.named) && page.speakers.length > 1 && " · speakers are unnamed until someone names them"}
          </p>
        )}

        {page?.can_use_recording_transcript && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed px-3 py-2 text-xs">
            <span className="text-muted-foreground">
              This meeting&apos;s recording has a timestamped transcript. Switch to it to enable click-to-play and subtitles.
            </span>
            <Button size="sm" variant="outline" onClick={() => setSwitchOpen(true)}>
              <ListRestart className="h-3.5 w-3.5" /> Use recording transcript
            </Button>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="relative">
        <div
          ref={listRef}
          onWheel={detach}
          onTouchMove={detach}
          onKeyDown={(event) => {
            if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key) && event.target === event.currentTarget) detach();
          }}
          tabIndex={-1}
          className="relative flex max-h-[70vh] flex-col gap-1 overflow-y-auto scroll-smooth pr-1 outline-none"
        >
          {segments.map((segment) => {
            const isActive = segment.id === activeId;
            const segmentComments = commentsBySegment.get(segment.id) ?? [];
            const lowConfidence = segment.confidence !== null && segment.confidence < LOW_CONFIDENCE;
            return (
              <div
                key={segment.id}
                id={`segment-${segment.id}`}
                ref={(node) => {
                  if (node) rowRefs.current.set(segment.id, node);
                  else rowRefs.current.delete(segment.id);
                }}
                className={`group rounded-md px-2.5 py-2 transition-[background-color,opacity] duration-300 [contain-intrinsic-size:auto_64px] [content-visibility:auto] ${
                  isActive ? "bg-primary/10" : "hover:bg-muted/50"
                } ${lyrics && !isActive ? "opacity-40 hover:opacity-100" : ""} ${flashId === segment.id ? "ring-2 ring-primary" : ""}`}
              >
                <div className="flex items-baseline gap-2">
                  {segment.start_ms !== null ? (
                    <button
                      type="button"
                      onClick={() => onSeek(segment.start_ms as number)}
                      disabled={!canPlay}
                      className="shrink-0 font-mono text-xs text-primary hover:underline disabled:cursor-default disabled:text-muted-foreground disabled:no-underline"
                      title={canPlay ? "Play from here" : "No recording to play"}
                    >
                      {formatClock(segment.start_ms)}
                    </button>
                  ) : null}
                  <span className={`shrink-0 text-xs font-semibold ${segment.speaker_named ? "" : "text-muted-foreground"}`}>
                    {segment.speaker}
                  </span>
                  {segment.edited && (
                    <Badge variant="outline" className="h-4 px-1 text-[10px]" title={`Originally: “${segment.original_text}”`}>
                      edited
                    </Badge>
                  )}
                  <div className="ml-auto flex shrink-0 gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    <Button variant="ghost" size="icon-sm" aria-label="Correct this line" onClick={() => { setEditing(segment.id); setDraft(segment.text); }}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label="Comment on this line" onClick={() => { setCommentingOn(segment.id); setCommentDraft(""); }}>
                      <MessageSquare className="h-3.5 w-3.5" />
                    </Button>
                    {segment.start_ms !== null && (
                      <Button variant="ghost" size="icon-sm" aria-label="Save this line as a clip" onClick={() => void clip(segment)}>
                        <Scissors className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    {segment.edited && (
                      <Button variant="ghost" size="icon-sm" aria-label="Restore the original text" onClick={() => void revert(segment)} disabled={saving}>
                        <Undo2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
                {editing === segment.id ? (
                  <div className="mt-1.5 flex flex-col gap-2">
                    <Textarea
                      value={draft}
                      autoFocus
                      rows={3}
                      aria-label="Corrected text"
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") setEditing(null);
                        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void saveEdit(segment);
                      }}
                    />
                    <div className="flex items-center gap-2">
                      <Button size="sm" onClick={() => void saveEdit(segment)} disabled={saving || !draft.trim()}>
                        <Check className="h-3.5 w-3.5" /> Save correction
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                      <span className="text-xs text-muted-foreground">The original ASR text is kept. AI notes will be marked out of date.</span>
                    </div>
                  </div>
                ) : (
                  <p
                    className={`mt-0.5 text-sm leading-relaxed ${lowConfidence ? "decoration-warning/60 decoration-dotted underline-offset-4 [text-decoration-line:underline]" : ""}`}
                    title={lowConfidence ? `Transcription confidence ${Math.round((segment.confidence as number) * 100)}% — check against the audio` : undefined}
                  >
                    {isActive && playing && !appliedQuery && getPlaybackMs && segment.start_ms !== null ? (
                      <KaraokeText
                        text={segment.text}
                        startMs={segment.start_ms}
                        endMs={segment.end_ms}
                        recorded={segment.word_times}
                        getPlaybackMs={getPlaybackMs}
                      />
                    ) : (
                      <Highlighted text={segment.text} query={appliedQuery} />
                    )}
                  </p>
                )}
                {(segmentComments.length > 0 || commentingOn === segment.id) && (
                  <div className="mt-2 flex flex-col gap-1.5 border-l-2 border-primary/20 pl-3">
                    {segmentComments.map((comment) => (
                      <div key={comment.id} className="flex items-start justify-between gap-2 text-xs">
                        <p><span className="font-medium">{comment.author}:</span> {comment.body}</p>
                        {comment.mine && (
                          <button type="button" aria-label="Delete comment" onClick={() => void removeComment(comment.id)} className="text-muted-foreground hover:text-destructive">
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    ))}
                    {commentingOn === segment.id && (
                      <div className="flex gap-2">
                        <Input
                          value={commentDraft}
                          autoFocus
                          onChange={(event) => setCommentDraft(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") void addComment(segment.id);
                            if (event.key === "Escape") setCommentingOn(null);
                          }}
                          placeholder="Add a comment for everyone in this meeting"
                          aria-label="Comment"
                          className="h-8"
                        />
                        <Button size="sm" onClick={() => void addComment(segment.id)} disabled={!commentDraft.trim()}>Post</Button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {segments.length === 0 && !loading && <p className="py-6 text-center text-sm text-muted-foreground">No lines match.</p>}
          {hasMore && (
            <Button variant="outline" size="sm" className="mt-2 self-center" disabled={loading} onClick={() => void load({ offset: segments.length })}>
              Load more
            </Button>
          )}
        </div>
        {playing && !follow && activeId && (
          <Button
            size="sm"
            className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md"
            onClick={() => {
              setFollow(true);
              centre(activeId);
            }}
          >
            <AudioLines className="h-3.5 w-3.5" /> Back to now playing
          </Button>
        )}
        </div>

        <details
          onToggle={(event) => {
            if ((event.target as HTMLDetailsElement).open && history === null) {
              api.getTranscriptHistory(meetingId).then(setHistory).catch(() => setHistory([]));
            }
          }}
        >
          <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <History className="h-3.5 w-3.5" /> Correction history
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {history === null && <Skeleton className="h-10 w-full" />}
            {history?.length === 0 && <p className="text-xs text-muted-foreground">No corrections yet — this is the transcript as it was captured.</p>}
            {history?.map((entry) => (
              <div key={entry.id} className="rounded-md border px-3 py-2 text-xs">
                <p className="text-muted-foreground">
                  {entry.edited_by ?? "Someone"} · {new Date(entry.created_at).toLocaleString()} · revision {entry.transcript_revision}
                  {entry.seq !== null && ` · line ${entry.seq + 1}`}
                </p>
                <p className="mt-1">
                  {entry.field === "speaker" ? "Speaker renamed: " : entry.field === "source" ? "Transcript replaced: " : ""}
                  <span className="text-muted-foreground line-through">{entry.old_value}</span> → {entry.new_value}
                </p>
              </div>
            ))}
          </div>
        </details>
      </div>

      <aside className="flex flex-col gap-4">
        <section className="rounded-lg border p-3">
          <h3 className="flex items-center gap-1.5 text-sm font-medium"><Bookmark className="h-4 w-4 text-primary" /> Bookmarks & clips</h3>
          {canPlay && (
            <div className="mt-2 flex gap-2">
              <Input
                value={bookmarkLabel}
                onChange={(event) => setBookmarkLabel(event.target.value)}
                placeholder={currentMs !== null ? `Label for ${formatClock(currentMs)}` : "Label"}
                aria-label="Bookmark label"
                className="h-8"
                onKeyDown={(event) => event.key === "Enter" && void bookmarkNow()}
              />
              <Button size="sm" variant="outline" onClick={() => void bookmarkNow()} disabled={currentMs === null}>Mark</Button>
            </div>
          )}
          <div className="mt-2 flex flex-col gap-1">
            {bookmarks.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {canPlay ? "Mark the current moment, or save any line as a clip." : "Save any line as a bookmark with the scissors button."}
              </p>
            )}
            {bookmarks.map((bookmark) => (
              <div key={bookmark.id} className="group flex items-start gap-2 rounded-md px-1.5 py-1 text-xs hover:bg-muted/50">
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-start gap-1.5 text-left"
                  disabled={bookmark.start_ms === null || !canPlay}
                  onClick={() => bookmark.start_ms !== null && onPlayRange(bookmark.start_ms, bookmark.end_ms)}
                >
                  <Play className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                  <span className="min-w-0">
                    <span className="font-mono text-muted-foreground">
                      {formatClock(bookmark.start_ms)}{bookmark.end_ms !== null && bookmark.end_ms !== bookmark.start_ms ? `–${formatClock(bookmark.end_ms)}` : ""}
                    </span>{" "}
                    <span className="break-words">{bookmark.label}</span>
                  </span>
                </button>
                {bookmark.mine && (
                  <button type="button" aria-label="Delete bookmark" onClick={() => void removeBookmark(bookmark.id)} className="text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive">
                    <Trash2 className="h-3 w-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border p-3">
          <h3 className="flex items-center gap-1.5 text-sm font-medium"><MessageSquare className="h-4 w-4 text-primary" /> Comments</h3>
          <div className="mt-2 flex flex-col gap-2">
            {comments.length === 0 && <p className="text-xs text-muted-foreground">Comment on any line, or on the meeting as a whole.</p>}
            {comments.map((comment) => (
              <div key={comment.id} className="text-xs">
                <p className="text-muted-foreground">
                  {comment.author}
                  {comment.start_ms !== null && (
                    <>
                      {" · "}
                      <button type="button" className="font-mono text-primary hover:underline" onClick={() => comment.segment_id && jumpTo(comment.segment_id)}>
                        {formatClock(comment.start_ms)}
                      </button>
                    </>
                  )}
                </p>
                {comment.quote && <p className="line-clamp-1 italic text-muted-foreground">“{comment.quote}”</p>}
                <p className="mt-0.5">{comment.body}</p>
              </div>
            ))}
            <div className="flex gap-2">
              <Input
                value={meetingCommentDraft}
                onChange={(event) => setMeetingCommentDraft(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && void addComment(null)}
                placeholder="Comment on the meeting"
                aria-label="Comment on the meeting"
                className="h-8"
              />
              <Button size="sm" variant="outline" onClick={() => void addComment(null)} disabled={!meetingCommentDraft.trim()}>Post</Button>
            </div>
          </div>
        </section>
      </aside>

      <Dialog open={renameOpen} onOpenChange={(next) => !saving && setRenameOpen(next)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Name speakers</DialogTitle>
            <DialogDescription>
              The transcript only knows that different voices spoke. Naming them is up to you — leave a field empty to keep the generic label.
            </DialogDescription>
          </DialogHeader>
          <datalist id="speaker-name-options">
            {attendees.map((person) => <option key={person.id} value={person.name} />)}
          </datalist>
          <div className="grid max-h-[50vh] gap-3 overflow-y-auto py-2">
            {page?.speakers.map((entry) => (
              <div key={entry.key} className="grid gap-1.5">
                <Label htmlFor={`speaker-name-${entry.key}`}>
                  {entry.generic} <span className="font-normal text-muted-foreground">· {entry.segment_count} lines</span>
                </Label>
                <Input
                  id={`speaker-name-${entry.key}`}
                  list="speaker-name-options"
                  value={speakerDraft[entry.key] ?? ""}
                  onChange={(event) => setSpeakerDraft((current) => ({ ...current, [entry.key]: event.target.value }))}
                  placeholder={entry.generic}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={() => void saveSpeakers()} disabled={saving}>{saving ? "Saving…" : "Save names"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={switchOpen} onOpenChange={(next) => !saving && setSwitchOpen(next)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Use the recording&apos;s transcript?</DialogTitle>
            <DialogDescription>
              The current transcript is replaced by the timestamped one from the recording. Speakers start as “Speaker 1, 2…” until you name them, and corrections made to the current text don&apos;t carry over. Evidence on tasks and decisions is re-linked by its quotes.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSwitchOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={() => void switchToRecording()} disabled={saving}>{saving ? "Switching…" : "Switch transcript"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );

  function jumpTo(segmentId: string) {
    const row = rowRefs.current.get(segmentId);
    if (!row) return;
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    setFlashId(segmentId);
    window.setTimeout(() => setFlashId(null), 2000);
    const segment = segments.find((item) => item.id === segmentId);
    if (canPlay && segment && segment.start_ms !== null) onSeek(segment.start_ms);
  }
}
