"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  MessageSquareText,
  Mic,
  Send,
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
import { MeetingAgenda } from "@/components/meeting-agenda";
import { RecordedMeetingCard } from "@/components/recorded-meeting-card";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";

type FocusItem =
  | { kind: "voice" }
  | { kind: "review"; meeting: MeetingSummary; count: number }
  | { kind: "task"; task: TaskListItem };

export default function HomePage() {
  const { user } = useAuth();
  const { captures, openNotetaker } = useShell();
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
    <div className="meeting-dashboard">
      <h1 className="sr-only">Your meetings</h1>
      {error && (
        <div className="dashboard-error" role="alert">
          <p>{error}</p>
          <button type="button" disabled={loading} onClick={() => void load()}>
            Try again
          </button>
        </div>
      )}
      <div className="dashboard-columns">
        <div className="dashboard-primary">
          <section className="meeting-shortcuts" aria-label="Start with Wilco">
            <button
              type="button"
              className="capture-tile"
              onClick={() => openNotetaker()}
            >
              <span className="capture-tile-icon">
                <Send aria-hidden="true" />
              </span>
              <strong>Capture a meeting</strong>
              <span className="capture-tile-description">
                Notes, tasks &amp; decisions.
              </span>
              <span className="capture-tile-cta">
                Invite Wilco{" "}
                <ChevronRight className="size-3.5" aria-hidden="true" />
              </span>
            </button>
            <div className="shortcut-stack">
              <Link href="/record" className="shortcut-tile">
                <span className="shortcut-icon" data-tone="record">
                  <Mic aria-hidden="true" />
                  <i />
                </span>
                <strong>
                  Record
                  <br />
                  in person
                </strong>
                <ArrowRight className="shortcut-arrow" aria-hidden="true" />
              </Link>
              <Link href="/memory" className="shortcut-tile">
                <span className="shortcut-icon">
                  <MessageSquareText aria-hidden="true" />
                </span>
                <strong>
                  Ask your
                  <br />
                  meetings
                </strong>
                <ArrowRight className="shortcut-arrow" aria-hidden="true" />
              </Link>
            </div>
          </section>

          {live.length > 0 && (
            <section className="dashboard-live" aria-label="Ongoing recordings">
              {live.map((capture) => (
                <Link
                  key={capture.id}
                  href={
                    capture.meeting_id
                      ? `/meetings/${capture.meeting_id}`
                      : "/meetings"
                  }
                >
                  <span className="recording-dot" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <strong>{capture.title || capture.meeting_code}</strong>
                    <small>{capture.status_label}</small>
                  </span>
                  <ChevronRight className="size-4" aria-hidden="true" />
                </Link>
              ))}
            </section>
          )}

          <section aria-labelledby="recent-heading">
            <div className="section-heading">
              <h2 id="recent-heading">Recent meetings</h2>
              <Link href="/meetings">View all</Link>
            </div>
            {loading ? (
              <div className="flex flex-col gap-4">
                <Skeleton className="h-48 rounded-3xl" />
                <Skeleton className="h-48 rounded-3xl" />
              </div>
            ) : !meetings?.length ? (
              <div className="recorded-empty">
                <Video className="size-7 text-primary" aria-hidden="true" />
                <h3>
                  {meetings === null
                    ? "Meetings couldn't load."
                    : "Your first meeting starts here."}
                </h3>
                <p>Invite Wilco, record in person, or upload a recording.</p>
                <Link
                  href="/meetings/new?source=upload"
                  className="violet-outline"
                >
                  Upload a recording
                </Link>
              </div>
            ) : (
              <div className="recorded-meeting-list">
                {meetings.slice(0, 3).map((meeting) => {
                  const review = queue.find(
                    (item) =>
                      item.kind === "review" && item.meeting.id === meeting.id,
                  );
                  return (
                    <RecordedMeetingCard key={meeting.id} meeting={meeting} review={Boolean(review)} />
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <div className="dashboard-secondary">
          <MeetingAgenda />
          <section className="next-step-panel" aria-labelledby="focus-heading">
            <div className="section-heading">
              <h2 id="focus-heading">
                Needs you{" "}
                {queue.length > 0 && (
                  <span className="small-count">{queue.length}</span>
                )}
              </h2>
              <Link href="/tasks">All tasks</Link>
            </div>
            <div aria-live="polite" aria-busy={loading || busy}>
              {loading ? (
                <Skeleton className="h-28 rounded-2xl" />
              ) : !active ? (
                <div className="next-step-empty">
                  <Check className="size-5 text-primary" aria-hidden="true" />
                  <span>
                    {error
                      ? "Your briefing is on hold."
                      : "You're all caught up."}
                  </span>
                </div>
              ) : (
                <div className="next-step-content">
                  <span className="next-step-kind">
                    {active.kind === "voice"
                      ? "Optional setup"
                      : active.kind === "review"
                        ? `${active.count} items to confirm`
                        : "Your next task"}
                  </span>
                  <h3>
                    {active.kind === "voice"
                      ? "Put a name to your voice"
                      : active.kind === "review"
                        ? active.meeting.title
                        : active.task.description}
                  </h3>
                  <p>
                    {active.kind === "voice"
                      ? "Record once for clearer speaker names."
                      : active.kind === "review"
                        ? "Check decisions, owners and speakers."
                        : formatDue(active.task)
                          ? `Due ${formatDue(active.task)}`
                          : active.task.meeting_title}
                  </p>
                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    {active.kind === "task" ? (
                      <>
                        <Button
                          size="lg"
                          onClick={() => void finishTask(active.task)}
                          disabled={busy}
                        >
                          <Check data-icon="inline-start" />
                          {busy ? "Saving…" : "Mark done"}
                        </Button>
                        <Link
                          href={`/tasks?task=${active.task.id}`}
                          className="text-xs text-muted-foreground"
                        >
                          Open task
                        </Link>
                      </>
                    ) : (
                      <Link
                        href={
                          active.kind === "voice"
                            ? "/voice-setup"
                            : `/meetings/${active.meeting.id}?review=1`
                        }
                        className="violet-button"
                      >
                        {active.kind === "voice"
                          ? "Set up voice"
                          : "Review meeting"}
                        <ArrowRight className="size-3.5" aria-hidden="true" />
                      </Link>
                    )}
                  </div>
                </div>
              )}
            </div>
            {queue.length > 1 && (
              <div className="next-step-pagination">
                <span>
                  {position + 1} of {queue.length}
                </span>
                <div>
                  <button
                    type="button"
                    aria-label="Previous item"
                    disabled={position === 0}
                    onClick={() => setCursor(position - 1)}
                  >
                    <ChevronLeft className="size-4" />
                  </button>
                  <button
                    type="button"
                    aria-label="Next item"
                    disabled={position >= queue.length - 1}
                    onClick={() => setCursor(position + 1)}
                  >
                    <ChevronRight className="size-4" />
                  </button>
                </div>
              </div>
            )}
          </section>
          <Link href="/meetings/new?source=upload" className="upload-shortcut">
            Have a recording already?{" "}
            <span>
              Upload it <ArrowRight className="size-3.5" aria-hidden="true" />
            </span>
          </Link>
        </div>
      </div>
    </div>
  );
}
