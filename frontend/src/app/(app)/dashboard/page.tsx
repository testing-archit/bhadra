"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  FileText,
  Loader2,
  MessageSquareText,
  Mic,
  Upload,
  Video,
} from "lucide-react";
import {
  api,
  type MeetingDetail,
  type MeetingSummary,
  type TaskListItem,
  type TaskUpdateResponse,
  type VoiceProfileStatus,
} from "@/lib/api";
import { WilcoMascot } from "@/components/brand";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { HomeFollowUps } from "@/components/home-follow-ups";
import { MeetingAgenda } from "@/components/meeting-agenda";
import { MeetingPeople } from "@/components/meeting-people";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";

const questionHref = (question: string) =>
  `/memory?q=${encodeURIComponent(question)}`;

export default function HomePage() {
  const router = useRouter();
  const { captures, openNotetaker } = useShell();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [latest, setLatest] = useState<MeetingDetail | null>(null);
  const [unknownSpeakers, setUnknownSpeakers] = useState<number | null>(null);
  const [voice, setVoice] = useState<VoiceProfileStatus | null>(null);
  const [question, setQuestion] = useState("");
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
        (row) =>
          row.processing_state !== "processing" &&
          row.processing_state !== "attention",
      );
      setLatest(null);
      setUnknownSpeakers(null);
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
      }
    }
    if (taskResult.status === "rejected" || meetingResult.status === "rejected")
      setError("Some of your work couldn’t load.");
    setLoading(false);
  }, []);
  useEffect(() => {
    void load();
    void api
      .getVoiceProfile()
      .then(setVoice)
      .catch(() => undefined);
  }, [load]);

  const recent =
    meetings?.find((meeting) => meeting.id === latest?.id) ??
    meetings?.find(
      (meeting) =>
        meeting.processing_state !== "processing" &&
        meeting.processing_state !== "attention",
    );
  const reviewCount =
    latest && unknownSpeakers !== null
      ? latest.tasks.filter((task) => !task.verified_at).length +
        latest.decisions.filter((decision) => !decision.verified_at).length +
        unknownSpeakers
      : null;
  const reviewHref = recent
    ? `/meetings/${recent.id}${reviewCount ? "?review=1" : ""}`
    : null;
  const live = captures.filter(
    (item) => isCaptureLive(item) && item.subscribed !== false,
  );
  function updateTask(updated: TaskUpdateResponse) {
    setTasks(
      (current) =>
        current?.map((task) =>
          task.id === updated.id ? { ...task, ...updated } : task,
        ) ?? null,
    );
  }

  return (
    <div className="meeting-dashboard home-return-workspace">
      <h1 className="sr-only">Your next steps</h1>
      {error && (
        <div className="dashboard-error" role="alert">
          <p>{error}</p>
          <button type="button" disabled={loading} onClick={() => void load()}>
            Try again
          </button>
        </div>
      )}
      <section
        className="mascot-welcome home-review-banner"
        aria-label="Meet Wilco"
      >
        <div className="mascot-welcome-copy">
          <span className="home-review-label">
            {recent
              ? "Your latest meeting"
              : meetings?.length === 0
                ? "Start with a meeting"
                : "Your meetings"}
          </span>
          {loading && meetings === null ? (
            <Skeleton className="h-8 w-64 max-w-full" />
          ) : (
            <h2>
              {recent?.title ??
                (meetings === null
                  ? "Your meeting notes"
                  : "Bring Wilco to your next meeting.")}
            </h2>
          )}
          {recent && (
            <p>
              {reviewCount === null
                ? "Open the notes and follow-ups."
                : reviewCount > 0
                  ? `${reviewCount} details to confirm`
                  : "Meeting details confirmed"}
            </p>
          )}
          <div className="home-review-actions">
            {recent && reviewHref && (
              <Link
                href={reviewHref}
                className={buttonVariants({ variant: "brand" })}
              >
                <FileText data-icon="inline-start" aria-hidden="true" />
                {reviewCount ? "Review notes" : "Open notes"}
              </Link>
            )}
            <Button
              variant={recent ? "outline" : "brand"}
              onClick={() => openNotetaker()}
            >
              <Video data-icon="inline-start" aria-hidden="true" />
              Invite Wilco
            </Button>
          </div>
        </div>
        <WilcoMascot className="welcome-mascot" />
      </section>

      {live.length > 0 && (
        <section
          className="dashboard-live home-live-strip"
          aria-label="Ongoing recordings"
        >
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
              <strong>{capture.title || capture.meeting_code}</strong>
              <small>{capture.status_label}</small>
              <ArrowRight aria-hidden="true" />
            </Link>
          ))}
        </section>
      )}

      <div className="home-action-grid">
        <HomeFollowUps
          tasks={tasks}
          loading={loading}
          onUpdated={updateTask}
          onRetry={() => void load()}
        />
        <div className="home-support-column">
          <MeetingAgenda compact />
          <section
            className="home-work-panel home-memory-panel"
            aria-labelledby="home-memory-heading"
          >
            <header className="home-panel-heading">
              <h2 id="home-memory-heading">
                <MessageSquareText aria-hidden="true" />
                Find it in your meetings
              </h2>
            </header>
            <form
              role="search"
              aria-label="Ask meeting memory"
              onSubmit={(event) => {
                event.preventDefault();
                if (question.trim()) router.push(questionHref(question.trim()));
              }}
            >
              <label className="sr-only" htmlFor="home-memory-question">
                Question about your meetings
              </label>
              <Input
                id="home-memory-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="What do you want to know?"
              />
              <Button
                type="submit"
                disabled={!question.trim()}
                aria-label="Ask Wilco"
              >
                <ArrowRight aria-hidden="true" />
              </Button>
            </form>
            <div className="home-question-links">
              {recent && (
                <Link
                  href={questionHref(
                    `What decisions were made in the meeting "${recent.title}"?`,
                  )}
                >
                  Decisions from your latest meeting
                  <ArrowRight aria-hidden="true" />
                </Link>
              )}
              <Link
                href={questionHref(
                  "Which follow-ups are still open from my meetings?",
                )}
              >
                Which follow-ups are still open?
                <ArrowRight aria-hidden="true" />
              </Link>
            </div>
          </section>
          <nav
            className="home-utility-links"
            aria-label="More ways to use Wilco"
          >
            <Link href="/record">
              <Mic aria-hidden="true" />
              Record in person
            </Link>
            <Link href="/meetings/new?source=upload">
              <Upload aria-hidden="true" />
              Upload recording
            </Link>
            {voice?.available && !voice.enrolled && (
              <Link href="/voice-setup">Optional voice setup</Link>
            )}
          </nav>
        </div>
      </div>

      <section
        className="home-work-panel home-recent-panel"
        aria-labelledby="recent-heading"
      >
        <header className="home-panel-heading">
          <h2 id="recent-heading">Recent notes</h2>
          <Link href="/meetings">
            View all
            <ArrowRight aria-hidden="true" />
          </Link>
        </header>
        {loading && !meetings ? (
          <Skeleton className="h-36 rounded-xl" />
        ) : !meetings?.length ? (
          <div className="home-small-empty">
            <Video aria-hidden="true" />
            <p>
              {meetings === null
                ? "Meetings couldn’t load."
                : "Notes from your meetings will appear here."}
            </p>
            <Link href="/meetings/new?source=upload">Upload a recording</Link>
          </div>
        ) : (
          <ul className="home-recent-list">
            {meetings.slice(0, 3).map((meeting) => {
              const processing = meeting.processing_state === "processing",
                attention = meeting.processing_state === "attention";
              return (
                <li key={meeting.id}>
                  <span className="home-note-icon">
                    <FileText aria-hidden="true" />
                  </span>
                  <Link
                    href={`/meetings/${meeting.id}${meeting.id === latest?.id && reviewCount ? "?review=1" : ""}`}
                    className="home-note-title"
                  >
                    <strong>{meeting.title}</strong>
                    <span>
                      {new Date(meeting.date).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                      })}
                      {meeting.duration_minutes > 0
                        ? ` · ${meeting.duration_minutes} min`
                        : ""}
                    </span>
                  </Link>
                  <span className="home-note-counts">
                    {meeting.task_count} follow-ups
                  </span>
                  <MeetingPeople
                    names={meeting.attendees.map((person) => person.name)}
                  />
                  <span className="home-note-status">
                    {processing ? (
                      <>
                        <Loader2
                          aria-hidden="true"
                          className="animate-spin motion-reduce:animate-none"
                        />
                        Processing
                      </>
                    ) : attention ? (
                      "Needs attention"
                    ) : meeting.id === latest?.id && reviewCount ? (
                      "Review"
                    ) : (
                      "Open notes"
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
