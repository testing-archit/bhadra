"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Bot, Check, ChevronLeft, ChevronRight, Mic, Sparkles, Video } from "lucide-react";
import { api, ApiError, type MeetingDetail, type MeetingSummary, type TaskListItem, type VoiceProfileStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { compareByUrgency, formatDue, isMyTask, taskDueDate } from "@/lib/tasks";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TwoTone, Waveform } from "@/components/brand";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";

type FocusItem = { kind: "voice" } | { kind: "review"; meeting: MeetingSummary; count: number } | { kind: "task"; task: TaskListItem };

const KIND_LABEL = { voice: "One-time setup", review: "Needs your review", task: "Your task" } as const;
const KIND_TINT = {
  voice: "bg-tint-sky text-tint-sky-foreground",
  review: "bg-tint-lilac text-tint-lilac-foreground",
  task: "bg-tint-peach text-tint-peach-foreground",
} as const;

function greetingFor(hour: number) {
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

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

  // Headline counts for the hero band. All three come from data already on
  // the page; nothing here is estimated.
  const counts = useMemo(() => {
    if (!tasks || !meetings) return null;
    const mine = tasks.filter((row) => row.status !== "done" && isMyTask(row, user));
    const now = Date.now();
    const weekAhead = now + 7 * 86_400_000;
    const weekAgo = now - 7 * 86_400_000;
    return {
      open: mine.length,
      dueSoon: mine.filter((row) => {
        const due = taskDueDate(row);
        return due !== null && due.getTime() <= weekAhead;
      }).length,
      meetings: meetings.filter((row) => new Date(row.date).getTime() >= weekAgo).length,
    };
  }, [tasks, meetings, user]);

  const position = Math.min(cursor, Math.max(0, queue.length - 1));
  const active = queue[position];
  const live = captures.find((item) => isCaptureLive(item) && item.subscribed !== false);
  const firstName = (user?.name || user?.email.split("@")[0] || "there").split(" ")[0];

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
    <div className="mx-auto flex max-w-6xl flex-col gap-6 pb-10">
      <header className="hero-band relative overflow-hidden rounded-[1.75rem] px-6 pt-7 pb-6 sm:px-9 sm:pt-9">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <p className="text-sm text-band-muted">{greetingFor(new Date().getHours())},</p>
            <h1 className="mt-1 truncate pb-1 text-5xl leading-[0.95] font-semibold tracking-[-0.04em] sm:text-7xl">{firstName}</h1>
            <p className="mt-3 max-w-md text-sm leading-6 text-band-muted">
              {tasks === null
                ? "Getting your briefing…"
                : queue.length
                  ? `${queue.length} ${queue.length === 1 ? "thing needs" : "things need"} you. One at a time.`
                  : "Nothing needs you right now."}
            </p>
          </div>
          <dl className="grid grid-cols-3 gap-6 sm:gap-10">
            {([
              ["Open", "tasks", counts?.open],
              ["Due", "within 7 days", counts?.dueSoon],
              ["Meetings", "last 7 days", counts?.meetings],
            ] as const).map(([lead, rest, value]) => (
              <div key={lead} className="min-w-0">
                <dt className="text-xs leading-tight font-medium text-band-foreground">
                  {lead}
                  <span className="block font-normal text-band-muted">{rest}</span>
                </dt>
                <dd className="font-dots mt-1 text-6xl leading-none sm:text-[5.25rem]">{value ?? "–"}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="mt-8 flex flex-col gap-5 border-t border-white/10 pt-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-4">
            <Waveform live={Boolean(live)} bars={live ? 18 : 28} className="h-9 shrink-0" />
            <p className="min-w-0 truncate text-sm text-band-muted" role={live ? "status" : undefined}>
              {live ? (
                <>
                  <span className="font-medium text-band-foreground">{live.title || live.meeting_code}</span> · Wilco is in the call
                </>
              ) : (
                "Ready for your next meeting"
              )}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Link
              href="/memory"
              className="inline-flex h-10 items-center gap-2 rounded-full border border-white/15 px-4 text-sm font-medium text-band-foreground transition-colors duration-150 hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-marigold/60 focus-visible:outline-none"
            >
              <Sparkles className="size-4" /> Ask memory
            </Link>
            <button
              type="button"
              onClick={() => openNotetaker()}
              className="inline-flex h-10 items-center gap-2 rounded-full bg-marigold px-4 text-sm font-semibold text-marigold-foreground transition-[background-color,transform] duration-150 hover:bg-marigold/90 active:scale-[0.98] focus-visible:ring-3 focus-visible:ring-marigold/60 focus-visible:outline-none"
            >
              <Bot className="size-4" /> Bring Wilco to a meeting
            </button>
          </div>
        </div>
      </header>

      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[1.45fr_1fr] lg:items-start">
        <section aria-label="Focused item" className="flex flex-col overflow-hidden rounded-[1.4rem] border bg-card">
          <div className="h-1 bg-muted">
            <div
              className="h-full bg-marigold transition-[width] duration-300 ease-out"
              style={{ width: queue.length ? `${((position + 1) / queue.length) * 100}%` : "100%" }}
            />
          </div>
          <div className="flex-1 p-6 sm:p-8" aria-live="polite">
            {tasks === null ? (
              <Skeleton className="h-52 w-full rounded-2xl" />
            ) : !active ? (
              <div className="flex min-h-56 flex-col items-start justify-center">
                <span className="mb-4 grid size-12 place-items-center rounded-2xl bg-tint-mint text-tint-mint-foreground"><Check className="size-6" /></span>
                <h2 className="font-heading text-2xl font-semibold tracking-tight">You&apos;re clear for now</h2>
                <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">New tasks and meetings that need your review will appear here.</p>
                <Link href="/meetings" className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold underline-offset-4 hover:underline">
                  Browse meetings <ArrowRight className="size-4" />
                </Link>
              </div>
            ) : (
              <div className="flex min-h-64 flex-col">
                <div className="flex items-center justify-between gap-4">
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${KIND_TINT[active.kind]}`}>{KIND_LABEL[active.kind]}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">{position + 1} of {queue.length}</span>
                </div>
                <h2 className="mt-6 max-w-3xl font-heading text-2xl leading-snug font-semibold tracking-tight sm:text-[1.9rem]">
                  {active.kind === "voice" ? "Let Wilco learn your voice" : active.kind === "review" ? `Review ${active.meeting.title}` : active.task.description}
                </h2>
                <p className="mt-3 text-sm text-muted-foreground">
                  {active.kind === "voice"
                    ? "A short recording helps name your speech in future meetings."
                    : active.kind === "review"
                      ? `${active.count} ${active.count === 1 ? "item" : "items"} to confirm or correct before the recap is ready.`
                      : `${active.task.meeting_title}${formatDue(active.task) ? ` · Due ${formatDue(active.task)}` : ""}`}
                </p>
                <div className="mt-auto flex flex-wrap items-center gap-3 pt-8">
                  {active.kind === "voice" ? (
                    <Link href="/voice-setup" className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/85">
                      Set up voice <ArrowRight className="size-4" />
                    </Link>
                  ) : active.kind === "review" ? (
                    <Link href={`/meetings/${active.meeting.id}?review=1`} className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/85">
                      Review now <ArrowRight className="size-4" />
                    </Link>
                  ) : (
                    <>
                      <Button size="lg" className="h-10 rounded-full px-5" onClick={() => void finishTask(active.task)} disabled={busy}>
                        <Check className="size-4" /> {busy ? "Saving…" : "Mark done"}
                      </Button>
                      <Link href={`/tasks?task=${active.task.id}`} className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
                        Open task
                      </Link>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
          {queue.length > 1 && (
            <div className="flex items-center justify-between border-t px-6 py-3 sm:px-8">
              <span className="text-xs text-muted-foreground">{queue.length - 1} more in your queue</span>
              <div className="flex gap-1">
                <button type="button" aria-label="Previous item" disabled={position === 0} onClick={() => setCursor(position - 1)} className="grid size-9 place-items-center rounded-full transition-colors hover:bg-muted disabled:opacity-30">
                  <ChevronLeft className="size-4" />
                </button>
                <button type="button" aria-label="Next item" disabled={position >= queue.length - 1} onClick={() => setCursor(position + 1)} className="grid size-9 place-items-center rounded-full transition-colors hover:bg-muted disabled:opacity-30">
                  <ChevronRight className="size-4" />
                </button>
              </div>
            </div>
          )}
        </section>

        <div className="flex flex-col gap-6">
          <section className="rounded-[1.4rem] border bg-card p-5">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-heading text-lg font-semibold tracking-tight"><TwoTone lead="Recent" rest="meetings" /></h2>
              <Link href="/meetings" className="text-xs font-semibold underline-offset-4 hover:underline">All meetings</Link>
            </div>
            {meetings === null ? (
              <Skeleton className="h-40 w-full rounded-xl" />
            ) : meetings.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">Your meetings will show up here.</p>
            ) : (
              <ul className="-mx-2 flex flex-col">
                {meetings.slice(0, 4).map((meeting) => (
                  <li key={meeting.id}>
                    <Link href={`/meetings/${meeting.id}`} className="group flex items-center gap-3 rounded-xl px-2 py-2.5 transition-colors hover:bg-muted">
                      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-tint-sky text-tint-sky-foreground"><Video className="size-4" /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{meeting.title}</span>
                        <span className="block text-xs text-muted-foreground">
                          {new Date(meeting.date).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
                        </span>
                      </span>
                      <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <div className="grid grid-cols-2 gap-3">
            <Link href="/memory" className="flex flex-col gap-6 rounded-[1.4rem] border bg-card p-4 transition-colors hover:bg-muted/60">
              <span className="grid size-10 place-items-center rounded-xl bg-tint-lilac text-tint-lilac-foreground"><Sparkles className="size-5" /></span>
              <span>
                <strong className="block text-sm font-semibold">Ask a meeting</strong>
                <span className="mt-0.5 block text-xs text-muted-foreground">Answers with sources</span>
              </span>
            </Link>
            <Link href="/record" className="flex flex-col gap-6 rounded-[1.4rem] border bg-card p-4 transition-colors hover:bg-muted/60">
              <span className="grid size-10 place-items-center rounded-xl bg-tint-peach text-tint-peach-foreground"><Mic className="size-5" /></span>
              <span>
                <strong className="block text-sm font-semibold">Record in person</strong>
                <span className="mt-0.5 block text-xs text-muted-foreground">Outside Meet or Teams</span>
              </span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
