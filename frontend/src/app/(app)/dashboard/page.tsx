"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Plus } from "lucide-react";
import {
  api,
  type MeetingDetail,
  type MeetingSummary,
  type TaskListItem,
  type TaskUpdateResponse,
  type TranscriptPage,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { dueBucket, isMyTask } from "@/lib/tasks";
import { type DebriefMark, formatMoment } from "@/lib/debrief-strip";
import { DebriefStrip, meetingMarks } from "@/components/meeting/debrief-strip";
import { HomeFollowUps } from "@/components/home-follow-ups";
import { HomeAsk } from "@/components/home-ask";
import { MeetingAgenda } from "@/components/meeting-agenda";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";

type MeetingContext = { detail: MeetingDetail; transcript: TranscriptPage };
const left = (n: number) =>
  n === 0
    ? "All clear."
    : `${["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"][n] ?? n} ${n === 1 ? "thing" : "things"} left.`;
const day = (value: string) =>
  new Date(value).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "Asia/Kolkata",
  });
function CountLink({
  count,
  label,
  href,
}: {
  count: number | null;
  label: string;
  href: string;
}) {
  return (
    <Link href={href} className="count-link">
      <strong>{count === null ? "—" : String(count).padStart(2, "0")}</strong>
      <span>{label}</span>
    </Link>
  );
}

export default function HomePage() {
  const { user } = useAuth();
  const { captures, openNotetaker } = useShell();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [context, setContext] = useState<Record<string, MeetingContext>>({});
  const [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null);
  const [moment, setMoment] = useState<DebriefMark | null>(null);
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
      setMoment(null);
      const selected = meetingResult.value
        .filter(
          (row) =>
            !["processing", "attention"].includes(row.processing_state ?? ""),
        )
        .slice(0, 3);
      const results = await Promise.allSettled(
        selected.map(async (row) => {
          const [detail, transcript] = await Promise.all([
            api.getMeeting(row.id),
            api.getTranscript(row.id, { limit: 500 }),
          ]);
          return { id: row.id, detail, transcript };
        }),
      );
      const next: Record<string, MeetingContext> = {};
      for (const result of results)
        if (result.status === "fulfilled") next[result.value.id] = result.value;
      setContext(next);
    }
    if (taskResult.status === "rejected" || meetingResult.status === "rejected")
      setError("Some work could not load.");
    setLoading(false);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const recent = (meetings ?? [])
    .filter(
      (row) =>
        !["processing", "attention"].includes(row.processing_state ?? ""),
    )
    .slice(0, 3);
  const latest = recent[0],
    current = latest && context[latest.id];
  const mine =
    tasks?.filter((task) => isMyTask(task, user) && task.status !== "done") ??
    [];
  const due = mine.filter((task) => dueBucket(task) === "today").length;
  const review = current
    ? current.detail.tasks.filter((row) => !row.verified_at).length +
      current.detail.decisions.filter((row) => !row.verified_at).length +
      current.transcript.speakers.filter(
        (row) => !row.named && row.segment_count > 0,
      ).length
    : null;
  const selected =
    moment &&
    current?.transcript.segments.find((row) => row.id === moment.segmentId);
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", {
      hour: "numeric",
      hourCycle: "h23",
      timeZone: "Asia/Kolkata",
    }).format(new Date()),
  );
  const greeting =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  function updated(value: TaskUpdateResponse) {
    setTasks(
      (rows) =>
        rows?.map((row) =>
          row.id === value.id ? { ...row, ...value } : row,
        ) ?? null,
    );
    window.dispatchEvent(new Event("wilco:tasks-changed"));
  }
  return (
    <div className="engagement-home">
      {error && (
        <p role="alert" className="engagement-error">
          {error}
          <button onClick={() => void load()}>Retry</button>
        </p>
      )}
      <section className="home-band ink-panel">
        <div className="home-band-copy">
          <h1>
            {greeting}, {user?.name?.split(" ")[0] ?? "there"}.
            <span>
              {tasks === null ? "Your next move." : left(mine.length)}
            </span>
          </h1>
          <div className="home-counts">
            <CountLink
              count={tasks === null ? null : mine.length}
              label="Yours"
              href="/tasks?scope=mine"
            />
            <CountLink
              count={tasks === null ? null : due}
              label="Due today"
              href="/tasks?due=today"
            />
            <CountLink
              count={review}
              label="To confirm"
              href={latest ? `/meetings/${latest.id}?review=1` : "/meetings"}
            />
          </div>
        </div>
        {latest ? (
          <div className="home-latest">
            <header>
              <h2>{latest.title}</h2>
              <span>
                {day(latest.date)} · {latest.duration_minutes} min
              </span>
            </header>
            {current && (
              <DebriefStrip
                segments={current.transcript.segments}
                marks={meetingMarks(
                  current.detail,
                  current.transcript.segments,
                )}
                duration_ms={latest.duration_minutes * 60000}
                variant="ink"
                onMarkClick={setMoment}
                selectedId={moment?.id}
              />
            )}
            <div className="home-latest-bottom">
              <div aria-live="polite">
                {selected ? (
                  <>
                    <time>{formatMoment(moment!.at_ms)}</time>
                    <p>“{selected.text}”</p>
                  </>
                ) : current ? (
                  <span>
                    {current.detail.decisions.length} decisions ·{" "}
                    {current.detail.tasks.length} tasks
                  </span>
                ) : (
                  <span>Loading moments…</span>
                )}
              </div>
              <Link
                href={`/meetings/${latest.id}?review=1`}
                className="signal-link"
              >
                Review
                <ArrowRight className="size-4" />
              </Link>
            </div>
          </div>
        ) : (
          <div className="home-latest home-first-meeting">
            {loading ? (
              <Skeleton className="h-32" />
            ) : (
              <>
                <img
                  src="/brand/wilco-mascot-v1.png"
                  alt=""
                  width={92}
                  height={92}
                />
                <h2>Bring Wilco to your next meeting.</h2>
                <Button variant="signal" onClick={() => openNotetaker()}>
                  <Plus />
                  Bring Wilco
                </Button>
              </>
            )}
          </div>
        )}
      </section>
      {captures
        .filter((row) => isCaptureLive(row) && row.subscribed !== false)
        .map((capture) => (
          <Link
            key={capture.id}
            href={`/meetings/live/${capture.id}`}
            className="home-live-notice"
          >
            <span className="recording-dot" />
            {capture.title || capture.meeting_code}
            <Badge variant="peach">{capture.status_label}</Badge>
            <ArrowRight className="size-4" />
          </Link>
        ))}
      <div className="home-work-grid">
        <HomeFollowUps
          tasks={tasks}
          loading={loading}
          onUpdated={updated}
          onRetry={() => void load()}
        />
        <div className="home-right-column">
          <MeetingAgenda compact />
          <HomeAsk />
        </div>
      </div>
      <section className="home-recent">
        <header className="sheet-heading">
          <h2>Recent meetings.</h2>
          <Link href="/meetings">
            All meetings
            <ArrowRight className="size-4" />
          </Link>
        </header>
        <div className="recent-tile-grid">
          {recent.map((row) => {
            const loaded = context[row.id],
              count = loaded
                ? loaded.detail.tasks.filter((task) => !task.verified_at)
                    .length +
                  loaded.detail.decisions.filter((item) => !item.verified_at)
                    .length
                : null;
            return (
              <Link
                key={row.id}
                href={`/meetings/${row.id}`}
                className="recent-meeting-tile work-sheet"
              >
                <div>
                  <h3>{row.title}</h3>
                  {count !== null && (
                    <Badge variant={count ? "peach" : "mint"}>
                      {count ? `${count} to confirm` : "Confirmed"}
                    </Badge>
                  )}
                </div>
                {loaded && (
                  <DebriefStrip
                    size="sm"
                    segments={loaded.transcript.segments}
                    marks={meetingMarks(
                      loaded.detail,
                      loaded.transcript.segments,
                    )}
                    duration_ms={row.duration_minutes * 60000}
                  />
                )}
                <span>
                  {day(row.date)} · {row.duration_minutes} min
                  {loaded
                    ? ` · ${loaded.detail.tasks.filter((task) => task.status !== "done").length} open`
                    : ""}
                </span>
              </Link>
            );
          })}
          {!loading && !recent.length && (
            <p className="text-sm text-muted-foreground">
              Your next meeting starts here.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
