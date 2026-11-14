"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  ListChecks,
  RefreshCw,
  Scale,
  Video,
} from "lucide-react";
import { api, ApiError, type Digest, type MeetingSummary, type TaskListItem } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { isTaskOverdue } from "@/lib/deadline";
import { compareByUrgency, formatDue, isMine } from "@/lib/tasks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { isCaptureLive, useShell } from "@/components/shell/shell-context";
import { UpcomingMeetings } from "@/components/upcoming-meetings";
import { PromptHero } from "@/components/prompt-hero";


function weekRange(digest: Digest) {
  const start = new Date(digest.week_start);
  const end = new Date(digest.week_end);
  end.setDate(end.getDate() - 1);
  const format = (date: Date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${format(start)} – ${format(end)}`;
}

export default function HomePage() {
  const { user } = useAuth();
  const { openNotetaker, captures } = useShell();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listTasks(), api.listMeetings()])
      .then(([taskList, meetingList]) => {
        setTasks(taskList);
        setMeetings(meetingList);
      })
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Your workspace could not be loaded."));
  }, []);

  const myTasks = useMemo(
    () => (tasks ?? []).filter((task) => task.status !== "done" && isMine(task, user)).sort(compareByUrgency),
    [tasks, user],
  );
  const live = captures.filter((item) => isCaptureLive(item) && item.subscribed !== false);
  const firstName = user?.name?.split(/\s+/)[0];

  async function completeTask(task: TaskListItem) {
    setTasks((current) => current?.map((item) => (item.id === task.id ? { ...item, status: "done" } : item)) ?? null);
    try {
      await api.updateTaskStatus(task.id, "done");
    } catch {
      setTasks((current) => current?.map((item) => (item.id === task.id ? task : item)) ?? null);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <PromptHero firstName={firstName} onCapture={() => openNotetaker()} />

      {live.length > 0 && (
        <section className="flex flex-col gap-3 rounded-2xl border border-primary/25 bg-primary/5 p-4 sm:flex-row sm:items-center">
          <span className="relative flex size-2.5 shrink-0">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive/60" />
            <span className="relative inline-flex size-2.5 rounded-full bg-destructive" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-medium">
              {live.length === 1 ? (live[0].title || live[0].meeting_code) : `${live.length} meetings in progress`}
            </p>
            <p className="text-sm text-muted-foreground">
              {live.length === 1 ? live[0].status_label : live.map((item) => item.title || item.meeting_code).join(", ")}
              . Notes appear here when the call ends.
            </p>
          </div>
        </section>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-8">
          {/* Reads ?brief= from a pre-meeting notification. */}
          <Suspense fallback={null}>
            <UpcomingMeetings />
          </Suspense>

          <section className="flex flex-col gap-3">
            <SectionHeading title="Your open tasks" count={tasks ? myTasks.length : undefined} href="/tasks?owner=me" linkLabel="All tasks" />
            {!tasks ? (
              <Skeleton className="h-48 w-full rounded-xl" />
            ) : myTasks.length === 0 ? (
              <div className="rounded-xl border border-dashed px-5 py-8 text-center">
                <ListChecks className="mx-auto size-5 text-muted-foreground" />
                <p className="mt-2 text-sm font-medium">Nothing assigned to you</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Tasks land here when someone names you as the owner in a meeting.
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-xl border bg-card">
                {myTasks.slice(0, 8).map((task) => {
                  const overdue = isTaskOverdue(task.deadline, task.meeting_date, task.status, task.due_date);
                  const due = formatDue(task);
                  return (
                    <div key={task.id} className="flex items-start gap-3 border-b px-4 py-3 last:border-b-0">
                      <Checkbox
                        className="mt-0.5"
                        checked={false}
                        onCheckedChange={() => void completeTask(task)}
                        aria-label={`Mark “${task.description}” done`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm leading-snug">{task.description}</p>
                        <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                          {due && (
                            <span className={cn(overdue && "flex items-center gap-1 font-medium text-destructive")}>
                              {overdue && <AlertTriangle className="size-3" />}
                              {overdue ? `Overdue, ${due}` : `Due ${due}`}
                            </span>
                          )}
                          {task.meeting_hidden ? (
                            <span className="truncate">{task.meeting_title}</span>
                          ) : (
                            <Link href={`/meetings/${task.meeting_id}`} className="truncate hover:text-foreground hover:underline">
                              {task.meeting_title}
                            </Link>
                          )}
                        </p>
                      </div>
                      {task.priority === "High" && (
                        <span className="shrink-0 rounded-md bg-destructive/10 px-1.5 py-0.5 text-xs font-medium text-destructive">High</span>
                      )}
                    </div>
                  );
                })}
                {myTasks.length > 8 && (
                  <Link href="/tasks?owner=me" className="block px-4 py-2.5 text-sm text-primary hover:bg-muted/50">
                    {myTasks.length - 8} more
                  </Link>
                )}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <SectionHeading title="Recent meetings" href="/meetings" linkLabel="All meetings" />
            {!meetings ? (
              <Skeleton className="h-56 w-full rounded-xl" />
            ) : meetings.length === 0 ? (
              <div className="rounded-xl border border-dashed px-5 py-8 text-center">
                <Video className="mx-auto size-5 text-muted-foreground" />
                <p className="mt-2 text-sm font-medium">No meetings yet</p>
                <p className="mt-1 text-sm text-muted-foreground">Send the notetaker into your next Google Meet or Teams call to get started.</p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-xl border bg-card">
                {meetings.slice(0, 5).map((meeting) => (
                  <Link
                    key={meeting.id}
                    href={`/meetings/${meeting.id}`}
                    className="group flex items-center gap-3 border-b px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/50"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium group-hover:text-primary">{meeting.title}</p>
                      <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{meeting.summary || "No summary yet"}</p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {new Date(meeting.date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>

        <WeekPanel />
      </div>
    </div>
  );
}

function SectionHeading({ title, count, href, linkLabel }: { title: string; count?: number; href: string; linkLabel: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h3 className="flex items-center gap-2 font-semibold">
        {title}
        {count !== undefined && count > 0 && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">{count}</span>
        )}
      </h3>
      <Link href={href} className="flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground">
        {linkLabel} <ArrowUpRight className="size-3.5" />
      </Link>
    </div>
  );
}

/** The weekly digest, folded into Home: what the team got through and what
 * it decided, one week at a time. */
function WeekPanel() {
  const [offset, setOffset] = useState(0);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDigest(null);
    api
      .getDigest(offset)
      .then((result) => !cancelled && setDigest(result))
      .catch((cause) => !cancelled && setError(cause instanceof ApiError ? cause.message : "The weekly digest could not be loaded."));
    return () => {
      cancelled = true;
    };
  }, [offset]);

  const stats = digest
    ? [
        { label: "Meetings", value: digest.meetings_count, icon: Video },
        { label: "Tasks done", value: digest.tasks_completed, icon: ListChecks },
        { label: "Decisions", value: digest.decisions_made, icon: Scale },
        { label: "Reversals", value: digest.contradictions_found, icon: RefreshCw },
      ]
    : [];

  return (
    <aside className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">{offset === 0 ? "This week" : offset === -1 ? "Last week" : "Week of"}</h3>
        <div className="flex items-center gap-1">
          <span className="mr-1 text-xs text-muted-foreground tabular-nums">{digest ? weekRange(digest) : ""}</span>
          <Button variant="ghost" size="icon-sm" onClick={() => setOffset((value) => value - 1)} aria-label="Previous week">
            <ChevronLeft />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setOffset((value) => value + 1)} disabled={offset >= 0} aria-label="Next week">
            <ChevronRight />
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="rounded-xl border bg-card">
        <div className="grid grid-cols-2">
          {digest
            ? stats.map((stat, index) => (
                <div key={stat.label} className={cn("flex flex-col gap-1 p-4", index % 2 === 0 && "border-r", index < 2 && "border-b")}>
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <stat.icon className="size-3.5" /> {stat.label}
                  </span>
                  <span className="text-2xl font-semibold tabular-nums">{stat.value}</span>
                </div>
              ))
            : [0, 1, 2, 3].map((index) => (
                <div key={index} className="p-4"><Skeleton className="h-10 w-full" /></div>
              ))}
        </div>

        {digest && digest.decisions.length > 0 && (
          <div className="border-t p-4">
            <p className="mb-2 text-xs font-medium text-muted-foreground">Decided</p>
            <ul className="flex flex-col gap-3">
              {digest.decisions.slice(0, 6).map((decision) => (
                <li key={decision.id} className="text-sm">
                  <Link href={`/meetings/${decision.meeting_id}`} className="leading-snug hover:text-primary">
                    {decision.decision}
                  </Link>
                  {decision.conflict_note && (
                    <p className="mt-1 flex items-start gap-1.5 text-xs text-warning">
                      <AlertTriangle className="mt-px size-3 shrink-0" />
                      {decision.conflict_note}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {digest && digest.meetings_count === 0 && (
          <p className="border-t p-4 text-sm text-muted-foreground">No meetings were captured this week.</p>
        )}
      </div>
    </aside>
  );
}
