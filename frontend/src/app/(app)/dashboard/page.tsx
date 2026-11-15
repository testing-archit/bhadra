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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { HomeFollowUps } from "@/components/home-follow-ups";
import { DemoTour } from "@/components/demo-tour";
import { MeetingAgenda } from "@/components/meeting-agenda";
import { MeetingPeople } from "@/components/meeting-people";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";
import "../../hackathon-home.css";

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
    <div className="meeting-dashboard home-return-workspace signal-room">
      <h1 className="sr-only">Meeting signal room</h1>
      <DemoTour />
      {error && (
        <div className="dashboard-error" role="alert">
          <p>{error}</p>
          <button type="button" disabled={loading} onClick={() => void load()}>
            Try again
          </button>
        </div>
      )}
      <section className="signal-hero" aria-labelledby="signal-hero-title">
        <div className="signal-hero-copy">
          <span className="signal-kicker"><span aria-hidden="true">//</span> Your team’s meeting intelligence</span>
          <h2 id="signal-hero-title">Turn meetings<br />into <em>shipped work.</em></h2>
          <p>Capture the conversation. Keep the decisions, context, and follow-ups your software team needs to move.</p>
          <div className="signal-hero-actions">
            <Button className="signal-primary-action" onClick={() => openNotetaker()}>
              <Video data-icon="inline-start" aria-hidden="true" />
              Join or start a meeting
              <ArrowRight aria-hidden="true" />
            </Button>
            {reviewHref && (
              <Link href={reviewHref} className="signal-secondary-action">
                <FileText aria-hidden="true" />
                {reviewCount ? "Review latest notes" : "Open latest notes"}
              </Link>
            )}
          </div>
          <div className="signal-hero-foot">
            {loading && meetings === null ? (
              <Skeleton className="h-9 w-64 max-w-full" />
            ) : recent ? (
              <Link href={reviewHref ?? `/meetings/${recent.id}`} className="signal-latest-link">
                <span className="signal-latest-icon"><FileText aria-hidden="true" /></span>
                <span><small>Latest meeting</small><strong>{recent.title}</strong></span>
                <span className="signal-latest-review">{reviewCount === null ? "Open notes" : reviewCount > 0 ? `${reviewCount} to confirm` : "Confirmed"}</span>
                <ArrowRight aria-hidden="true" />
              </Link>
            ) : (
              <span className="signal-hero-empty">{meetings === null ? "Meeting notes unavailable right now." : "Your first meeting will appear here."}</span>
            )}
          </div>
        </div>
        <div className="signal-art" aria-hidden="true">
          <div className="signal-art-grid" />
          <svg className="signal-wave" viewBox="0 0 780 480" preserveAspectRatio="xMidYMid meet">
            <defs>
              <linearGradient id="signal-wave-a" x1="0" y1="1" x2="1" y2="0"><stop offset="0"/><stop offset=".48"/><stop offset="1"/></linearGradient>
              <linearGradient id="signal-wave-b" x1="0" y1="1" x2="1" y2="0"><stop offset="0"/><stop offset=".65"/><stop offset="1"/></linearGradient>
              <filter id="signal-glow"><feGaussianBlur stdDeviation="13" /></filter>
            </defs>
            <path className="signal-wave-glow" d="M0 333 C65 334 80 276 133 306 S225 367 276 270 S365 236 400 280 S473 360 522 191 S607 278 651 178 S718 175 780 158" stroke="url(#signal-wave-a)" filter="url(#signal-glow)" />
            <path className="signal-wave-fill" d="M0 333 C65 334 80 276 133 306 S225 367 276 270 S365 236 400 280 S473 360 522 191 S607 278 651 178 S718 175 780 158 L780 435 L0 435 Z" fill="url(#signal-wave-b)" />
            <path className="signal-wave-main" d="M0 333 C65 334 80 276 133 306 S225 367 276 270 S365 236 400 280 S473 360 522 191 S607 278 651 178 S718 175 780 158" stroke="url(#signal-wave-a)" />
            <path className="signal-wave-secondary" d="M0 360 C90 340 133 359 211 340 S333 300 402 320 S514 326 581 247 S690 246 780 223" />
            <g className="signal-node"><circle cx="276" cy="270" r="7"/><circle cx="522" cy="191" r="7"/><circle cx="651" cy="178" r="7"/></g>
          </svg>
          <span className="signal-stage signal-stage-one"><i />Discussion</span>
          <span className="signal-stage signal-stage-two"><i />Decision</span>
          <span className="signal-stage signal-stage-three"><i />Action</span>
          <span className="signal-art-caption">From discussion to decisions to action</span>
        </div>
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

      <div className="signal-section-heading"><span>What needs your attention</span><Link href="/tasks">Open all tasks <ArrowRight aria-hidden="true" /></Link></div>
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
                Ask your meeting memory
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
                placeholder="Why did we choose that approach?"
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
