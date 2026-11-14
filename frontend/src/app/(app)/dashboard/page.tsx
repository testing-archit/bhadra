"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Bot, Check, ChevronLeft, ChevronRight, Mic, Sparkles, Video } from "lucide-react";
import { api, ApiError, type MeetingDetail, type MeetingSummary, type TaskListItem, type VoiceProfileStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { compareByUrgency, formatDue, isMyTask } from "@/lib/tasks";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";

type FocusItem = { kind: "voice" } | { kind: "review"; meeting: MeetingSummary; count: number } | { kind: "task"; task: TaskListItem };

export default function HomePage() {
  const { user } = useAuth();
  const { openNotetaker, captures } = useShell();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [latest, setLatest] = useState<MeetingDetail | null>(null);
  const [unknownSpeakers, setUnknownSpeakers] = useState(0);
  const [voice, setVoice] = useState<VoiceProfileStatus | null>(null);
  const [cursor, setCursor] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.getVoiceProfile().then(setVoice).catch(() => undefined);
    Promise.all([api.listTasks(), api.listMeetings()]).then(([taskRows, meetingRows]) => {
      setTasks(taskRows);
      setMeetings(meetingRows);
      if (meetingRows[0] && meetingRows[0].processing_state !== "processing") {
        void api.getMeeting(meetingRows[0].id).then(setLatest).catch(() => undefined);
        void api.getTranscript(meetingRows[0].id, { limit: 1 }).then((page) =>
          setUnknownSpeakers(page.speakers.filter((speaker) => !speaker.named && speaker.segment_count > 0).length)
        ).catch(() => undefined);
      }
    }).catch((cause) => setError(cause instanceof ApiError ? cause.message : "Your briefing could not be loaded."));
  }, []);

  const queue = useMemo(() => {
    const items: FocusItem[] = [];
    if (voice?.available && !voice.enrolled) items.push({ kind: "voice" });
    if (latest && meetings?.[0]?.id === latest.id) {
      const count = latest.tasks.filter((task) => !task.verified_at).length
        + latest.decisions.filter((decision) => !decision.verified_at).length + unknownSpeakers;
      if (count) items.push({ kind: "review", meeting: meetings[0], count });
    }
    for (const task of (tasks ?? []).filter((row) => row.status !== "done" && isMyTask(row, user)).sort(compareByUrgency)) {
      items.push({ kind: "task", task });
    }
    return items;
  }, [latest, meetings, tasks, user, voice, unknownSpeakers]);
  const position = Math.min(cursor, Math.max(0, queue.length - 1));
  const active = queue[position];
  const live = captures.find((item) => isCaptureLive(item) && item.subscribed !== false);

  async function finishTask(task: TaskListItem) {
    setBusy(true);
    setError(null);
    try {
      await api.updateTaskStatus(task.id, "done");
      setTasks((current) => current?.filter((row) => row.id !== task.id) ?? null);
      setCursor(0);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not complete this task.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 pb-10">
      <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">Your briefing</p>
          <h1 className="mt-2 font-heading text-4xl font-semibold tracking-tight sm:text-5xl">What needs me?</h1>
          <p className="mt-2 text-sm text-muted-foreground">One thing at a time. The rest can wait.</p>
        </div>
        <Button onClick={() => openNotetaker()} className="shrink-0"><Bot className="size-4" /> Bring Charcha to a meeting</Button>
      </header>

      {live && <div className="flex items-center gap-3 rounded-2xl border border-primary/25 bg-primary/5 px-4 py-3" role="status"><span className="size-2.5 animate-pulse rounded-full bg-destructive" /><p className="min-w-0 flex-1 truncate text-sm"><strong>{live.title || live.meeting_code}</strong> · Charcha is in the call</p></div>}

      <section aria-label="Focused item" className="overflow-hidden rounded-3xl border bg-card shadow-sm">
        <div className="h-1.5 bg-primary/10"><div className="h-full bg-primary transition-all" style={{ width: queue.length ? `${((position + 1) / queue.length) * 100}%` : "100%" }} /></div>
        <div className="min-h-76 p-6 sm:p-9" aria-live="polite">
          {tasks === null ? <Skeleton className="h-48 w-full rounded-2xl" /> : !active ? (
            <div className="flex min-h-56 flex-col items-start justify-center">
              <span className="mb-4 grid size-12 place-items-center rounded-2xl bg-success/10 text-success"><Check className="size-6" /></span>
              <h2 className="font-heading text-2xl font-semibold">You&apos;re clear for now</h2>
              <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">New tasks and meetings that need your review will appear here.</p>
              <Link href="/meetings" className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">Browse meetings <ArrowRight className="size-4" /></Link>
            </div>
          ) : (
            <div className="flex min-h-56 flex-col">
              <div className="flex items-center justify-between gap-4"><span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">{active.kind === "voice" ? "One-time setup" : active.kind === "review" ? "Needs your review" : "Your task"}</span><span className="font-mono text-xs tabular-nums text-muted-foreground">{position + 1} / {queue.length}</span></div>
              <h2 className="mt-7 max-w-3xl font-heading text-2xl font-semibold leading-snug sm:text-3xl">{active.kind === "voice" ? "Let Charcha learn your voice" : active.kind === "review" ? `Review ${active.meeting.title}` : active.task.description}</h2>
              <p className="mt-3 text-sm text-muted-foreground">{active.kind === "voice" ? "A short recording helps name your speech in future meetings." : active.kind === "review" ? `${active.count} ${active.count === 1 ? "item" : "items"} to confirm or correct before the recap is ready.` : `${active.task.meeting_title}${formatDue(active.task) ? ` · Due ${formatDue(active.task)}` : ""}`}</p>
              <div className="mt-auto flex flex-wrap items-center gap-3 pt-8">
                {active.kind === "voice" ? <Link href="/voice-setup" className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90">Set up voice <ArrowRight className="size-4" /></Link> : active.kind === "review" ? <Link href={`/meetings/${active.meeting.id}?review=1`} className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90">Review now <ArrowRight className="size-4" /></Link> : <>
                  <Button onClick={() => void finishTask(active.task)} disabled={busy}><Check className="size-4" /> {busy ? "Saving…" : "Mark done"}</Button>
                  <Link href={`/tasks?task=${active.task.id}`} className="text-sm font-medium text-muted-foreground hover:text-foreground">Open task</Link>
                </>}
              </div>
            </div>
          )}
        </div>
        {queue.length > 1 && <div className="flex items-center justify-between border-t px-5 py-3 sm:px-9"><span className="text-xs text-muted-foreground">{queue.length - 1} more in your queue</span><div className="flex gap-1"><button type="button" aria-label="Previous item" disabled={position === 0} onClick={() => setCursor(position - 1)} className="grid size-9 place-items-center rounded-full hover:bg-muted disabled:opacity-30"><ChevronLeft className="size-4" /></button><button type="button" aria-label="Next item" disabled={position >= queue.length - 1} onClick={() => setCursor(position + 1)} className="grid size-9 place-items-center rounded-full hover:bg-muted disabled:opacity-30"><ChevronRight className="size-4" /></button></div></div>}
      </section>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <Link href="/memory" className="group flex items-center gap-4 rounded-2xl border bg-card/60 p-5 transition-colors hover:bg-card"><span className="grid size-11 place-items-center rounded-xl bg-primary/10 text-primary"><Sparkles className="size-5" /></span><span className="flex-1"><strong className="block text-sm">Ask about any meeting</strong><span className="mt-1 block text-xs text-muted-foreground">Find an answer with its source</span></span><ArrowRight className="size-4 text-muted-foreground group-hover:text-primary" /></Link>
        <Link href="/record" className="group flex items-center gap-4 rounded-2xl border bg-card/60 p-5 transition-colors hover:bg-card"><span className="grid size-11 place-items-center rounded-xl bg-primary/10 text-primary"><Mic className="size-5" /></span><span className="flex-1"><strong className="block text-sm">Record in person</strong><span className="mt-1 block text-xs text-muted-foreground">For conversations outside Meet</span></span><ArrowRight className="size-4 text-muted-foreground group-hover:text-primary" /></Link>
      </div>
      <section><div className="mb-3 flex items-center justify-between"><h2 className="font-heading text-lg font-semibold">Recent meetings</h2><Link href="/meetings" className="text-xs font-semibold text-primary hover:underline">All meetings</Link></div><div className="overflow-hidden rounded-2xl border bg-card/60">{meetings === null ? <Skeleton className="h-20 w-full" /> : meetings.length === 0 ? <p className="px-5 py-8 text-sm text-muted-foreground">Your meetings will show up here.</p> : meetings.slice(0, 3).map((meeting) => <Link key={meeting.id} href={`/meetings/${meeting.id}`} className="group flex items-center gap-3 border-b px-5 py-4 last:border-0 hover:bg-muted/50"><Video className="size-4 shrink-0 text-muted-foreground" /><span className="min-w-0 flex-1 truncate text-sm font-medium">{meeting.title}</span><span className="text-xs text-muted-foreground">{new Date(meeting.date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span><ArrowRight className="size-4 text-muted-foreground group-hover:text-primary" /></Link>)}</div></section>
    </div>
  );
}
