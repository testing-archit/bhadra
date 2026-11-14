"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Headphones,
  ListChecks,
  Mic,
  Video,
} from "lucide-react";
import {
  api,
  ApiError,
  type MeetingDetail,
  type MeetingSummary,
  type TaskListItem,
  type VoiceProfileStatus,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { compareByUrgency, formatDue, isMyTask } from "@/lib/tasks";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { HomeComposer } from "@/components/home-composer";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";

type FocusItem =
  | { kind: "voice" }
  | { kind: "review"; meeting: MeetingSummary; count: number }
  | { kind: "task"; task: TaskListItem };

export default function HomePage() {
  const { user } = useAuth();
  const { captures } = useShell();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [latest, setLatest] = useState<MeetingDetail | null>(null);
  const [unknownSpeakers, setUnknownSpeakers] = useState(0);
  const [voice, setVoice] = useState<VoiceProfileStatus | null>(null);
  const [cursor, setCursor] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [taskResult, meetingResult] = await Promise.allSettled([
      api.listTasks(),
      api.listMeetings(),
    ]);
    if (taskResult.status === "fulfilled") setTasks(taskResult.value);
    if (meetingResult.status === "fulfilled") {
      setMeetings(meetingResult.value);
      const first = meetingResult.value.find(
        (row) => row.processing_state !== "processing",
      );
      if (first) {
        void api
          .getMeeting(first.id)
          .then(setLatest)
          .catch(() => undefined);
        void api
          .getTranscript(first.id, { limit: 1 })
          .then((page) =>
            setUnknownSpeakers(
              page.speakers.filter(
                (speaker) => !speaker.named && speaker.segment_count > 0,
              ).length,
            ),
          )
          .catch(() => undefined);
      } else {
        setLatest(null);
        setUnknownSpeakers(0);
      }
    }
    if (taskResult.status === "rejected" || meetingResult.status === "rejected")
      setError("Some of your briefing couldn't load.");
    setLoading(false);
  }, []);
  useEffect(() => {
    void load();
    void api
      .getVoiceProfile()
      .then(setVoice)
      .catch(() => undefined);
  }, [load]);

  const queue = useMemo(() => {
    const items: FocusItem[] = [];
    const meeting = meetings?.find((row) => row.id === latest?.id);
    if (latest && meeting) {
      const count =
        latest.tasks.filter((task) => !task.verified_at).length +
        latest.decisions.filter((decision) => !decision.verified_at).length +
        unknownSpeakers;
      if (count) items.push({ kind: "review", meeting, count });
    }
    for (const task of (tasks ?? [])
      .filter((row) => row.status !== "done" && isMyTask(row, user))
      .sort(compareByUrgency))
      items.push({ kind: "task", task });
    if (voice?.available && !voice.enrolled) items.push({ kind: "voice" });
    return items;
  }, [latest, meetings, tasks, user, voice, unknownSpeakers]);
  const position = Math.min(cursor, Math.max(0, queue.length - 1));
  const active = queue[position];
  const live = captures.filter(
    (item) => isCaptureLive(item) && item.subscribed !== false,
  );
  const firstName = (user?.name || user?.email.split("@")[0] || "there").split(
    " ",
  )[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Morning" : hour < 17 ? "Afternoon" : "Evening";

  async function finishTask(task: TaskListItem) {
    setBusy(true);
    setError(null);
    try {
      await api.updateTaskStatus(task.id, "done");
      setTasks(
        (current) => current?.filter((row) => row.id !== task.id) ?? null,
      );
      setCursor(0);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Couldn't complete the task. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="home-workspace">
      <section className="home-stage" aria-labelledby="home-heading">
        <div className="home-atmosphere" aria-hidden="true" />
        <div className="relative flex w-full max-w-2xl flex-col items-center">
          <p className="mb-5 text-sm text-muted-foreground">
            {greeting}, {firstName}.
          </p>
          <h1
            id="home-heading"
            className="text-center text-[clamp(2rem,4vw,3.25rem)] leading-[1.06] font-medium tracking-[-0.055em]"
          >
            Be in the conversation.
          </h1>
          <p className="mt-4 text-center text-base text-muted-foreground">
            We&apos;ll remember what matters.
          </p>
          <div className="mt-7 w-full">
            <HomeComposer />
          </div>
        </div>
      </section>

      {live.length > 0 && (
        <div
          className="mb-7 flex flex-col gap-2"
          aria-label="Active notetakers"
        >
          {live.map((capture) => (
            <Link
              key={capture.id}
              href={
                capture.meeting_id
                  ? `/meetings/${capture.meeting_id}`
                  : "/meetings"
              }
              className="live-meeting-strip"
            >
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-success/10 text-success">
                <Headphones className="size-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {capture.title || capture.meeting_code}
                </span>
                <span className="block text-xs text-muted-foreground">
                  {capture.status_label}
                </span>
              </span>
              <span className="text-xs text-muted-foreground">
                {capture.status === "capturing" ? "Recording" : "View status"}
              </span>
              <ArrowUpRight className="size-4" aria-hidden="true" />
            </Link>
          ))}
        </div>
      )}

      {error && (
        <div
          className="mb-5 flex items-center justify-between gap-3 rounded-xl border border-destructive/30 p-3 text-sm"
          role="alert"
        >
          <p>{error}</p>
          <button
            type="button"
            disabled={loading}
            onClick={() => void load()}
            className="shrink-0 font-medium underline underline-offset-4"
          >
            Try again
          </button>
        </div>
      )}

      <div className="home-lower-grid">
        <section className="focus-panel" aria-labelledby="focus-heading">
          <div className="flex items-center justify-between gap-3">
            <h2 id="focus-heading" className="text-sm font-medium">
              Needs you{" "}
              <span className="ml-2 text-muted-foreground">
                {loading ? "" : queue.length}
              </span>
            </h2>
            <Link href="/tasks" className="quiet-link">
              All tasks <ArrowUpRight className="size-3.5" aria-hidden="true" />
            </Link>
          </div>
          <div
            className="flex min-h-60 flex-1 flex-col justify-center py-6"
            aria-live="polite"
            aria-busy={loading || busy}
          >
            {loading ? (
              <Skeleton className="h-36 w-full rounded-xl" />
            ) : !active ? (
              <>
                <span className="mb-5 grid size-10 place-items-center rounded-full bg-success/10 text-success">
                  <Check className="size-5" aria-hidden="true" />
                </span>
                <h3 className="text-2xl font-medium tracking-tight">
                  {error
                    ? "Your briefing is on hold."
                    : "A little breathing room."}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  {error
                    ? "Try loading it again above."
                    : "You're all caught up."}
                </p>
              </>
            ) : (
              <>
                <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
                  {active.kind === "review" ? (
                    <Video className="size-4" />
                  ) : active.kind === "task" ? (
                    <ListChecks className="size-4" />
                  ) : (
                    <Mic className="size-4" />
                  )}
                  {active.kind === "review"
                    ? `${active.count} to confirm`
                    : active.kind === "task"
                      ? "Your next task"
                      : "Optional voice setup"}
                </div>
                <h3 className="max-w-xl text-2xl leading-snug font-medium tracking-tight">
                  {active.kind === "voice"
                    ? "Put a name to your voice."
                    : active.kind === "review"
                      ? active.meeting.title
                      : active.task.description}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  {active.kind === "voice"
                    ? "Record once. Get better speaker names."
                    : active.kind === "review"
                      ? "Check the decisions, owners and names."
                      : [
                          active.task.meeting_title,
                          formatDue(active.task) &&
                            `Due ${formatDue(active.task)}`,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                </p>
                <div className="mt-6 flex flex-wrap items-center gap-4">
                  {active.kind === "task" ? (
                    <>
                      <Button
                        size="lg"
                        disabled={busy}
                        onClick={() => void finishTask(active.task)}
                      >
                        <Check data-icon="inline-start" />
                        {busy ? "Saving…" : "Mark done"}
                      </Button>
                      <Link
                        href={`/tasks?task=${active.task.id}`}
                        className="quiet-link"
                      >
                        Open task <ArrowUpRight className="size-3.5" />
                      </Link>
                    </>
                  ) : (
                    <Link
                      href={
                        active.kind === "voice"
                          ? "/voice-setup"
                          : `/meetings/${active.meeting.id}?review=1`
                      }
                      className="focus-action"
                    >
                      {active.kind === "voice"
                        ? "Set up voice"
                        : "Review meeting"}
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  )}
                </div>
              </>
            )}
          </div>
          <div className="flex min-h-10 items-center justify-between border-t pt-4">
            <p className="text-xs text-muted-foreground">
              {queue.length
                ? `${position + 1} of ${queue.length}`
                : "Nothing to chase."}
            </p>
            {queue.length > 1 && (
              <div className="flex gap-1">
                <button
                  type="button"
                  aria-label="Previous item"
                  disabled={position === 0}
                  onClick={() => setCursor(position - 1)}
                  className="focus-step"
                >
                  <ChevronLeft className="size-4" />
                </button>
                <button
                  type="button"
                  aria-label="Next item"
                  disabled={position === queue.length - 1}
                  onClick={() => setCursor(position + 1)}
                  className="focus-step"
                >
                  <ChevronRight className="size-4" />
                </button>
              </div>
            )}
          </div>
        </section>
        <section className="recent-panel" aria-labelledby="recent-heading">
          <div className="mb-4 flex items-center justify-between">
            <h2 id="recent-heading" className="text-sm font-medium">
              Recent conversations
            </h2>
            <Link href="/meetings" className="quiet-link">
              View all <ArrowUpRight className="size-3.5" />
            </Link>
          </div>
          {loading ? (
            <Skeleton className="h-52 w-full rounded-xl" />
          ) : !meetings?.length ? (
            <p className="py-10 text-sm text-muted-foreground">
              {meetings === null
                ? "Meetings couldn't load."
                : "Your first conversation starts above."}
            </p>
          ) : (
            <ul className="flex flex-col">
              {meetings.slice(0, 4).map((meeting, index) => (
                <li key={meeting.id}>
                  <Link
                    href={`/meetings/${meeting.id}`}
                    className="recent-meeting-row"
                  >
                    <span className="meeting-glyph" data-tone={index % 3}>
                      <Video className="size-4" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {meeting.title}
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {new Date(meeting.date).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                        })}
                        {meeting.duration_minutes
                          ? ` · ${meeting.duration_minutes} min`
                          : ""}
                        {meeting.processing_state === "processing"
                          ? " · Processing"
                          : ""}
                      </span>
                    </span>
                    <ArrowUpRight
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Link
            href="/meetings?view=calendar"
            className="mt-5 inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
          >
            See what&apos;s coming up{" "}
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        </section>
      </div>
    </div>
  );
}
