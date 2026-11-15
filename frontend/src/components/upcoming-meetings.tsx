"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowUpRight, CalendarDays, ChevronDown, NotebookPen, Users } from "lucide-react";
import { api, type CalendarEventItem, type CalendarState, type ChatSource, type PreMeetingBrief } from "@/lib/api";
import { ListenInLanguage } from "@/components/listen-in-language";
import { CitedMarkdown } from "@/components/cited-markdown";
import { RecordSwitch } from "@/components/record-switch";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function dayLabel(date: Date) {
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === tomorrow.toDateString()) return "Tomorrow";
  return date.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

function timeRange(event: CalendarEventItem) {
  const format = (value: string) => new Date(value).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${format(event.start_at)} – ${format(event.end_at)}`;
}

const MAX_BRIEF_TASKS = 5;

/** The automatic pre-meeting brief, cited against the earlier meetings it
 * was built from. */
function BriefPanel({ brief }: { brief: PreMeetingBrief }) {
  const router = useRouter();
  if (brief.status === "failed" || !brief.text) {
    return <p className="text-sm text-muted-foreground">The brief couldn&apos;t be written{brief.error ? `: ${brief.error}` : "."}</p>;
  }
  const sources: ChatSource[] = brief.meetings.map((meeting) => ({
    meeting_id: meeting.id,
    meeting_title: meeting.title,
    meeting_date: meeting.date,
    tag: meeting.tag,
  }));
  return (
    <div className="flex flex-col gap-3">
      <ListenInLanguage text={[brief.text.replace(/\[M\d+\]/g, ""), ...brief.open_tasks.map((task) => `Open item: ${task.description}. Owner: ${task.owner || "not stated"}${task.deadline ? `. Due ${task.deadline}` : ""}.`)].join(" ").slice(0, 6000)} listenLabel="Listen to your brief" share={false} />
      <CitedMarkdown
        content={brief.text}
        sources={sources}
        onCite={(citation) => citation.source.meeting_id && router.push(`/meetings/${citation.source.meeting_id}`)}
      />
      {brief.open_tasks.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-muted-foreground">Open tasks</p>
          {brief.open_tasks.slice(0, MAX_BRIEF_TASKS).map((task) => (
            <p key={task.id} className="text-sm">
              {task.description}
              <span className="text-xs text-muted-foreground">
                {" "}· {task.owner || "owner not stated"}
                {task.deadline && ` · due ${task.deadline}`}
              </span>
            </p>
          ))}
          {brief.open_tasks.length > MAX_BRIEF_TASKS && (
            <p className="text-xs text-muted-foreground">and {brief.open_tasks.length - MAX_BRIEF_TASKS} more</p>
          )}
        </div>
      )}
      <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        From:
        {brief.meetings.map((meeting) => (
          <Link key={meeting.id} href={`/meetings/${meeting.id}`} className="hover:text-foreground hover:underline">
            {meeting.tag} {meeting.title}
            {meeting.previous_occurrence ? " (last time)" : ""}
          </Link>
        ))}
      </p>
    </div>
  );
}

/** What the notetaker will do in each upcoming calendar meeting, with a
 * switch per meeting and, shortly before it starts, a brief. Shown on Home
 * once a calendar is linked. */
export function UpcomingMeetings() {
  const [state, setState] = useState<CalendarState | null>(null);
  const [events, setEvents] = useState<CalendarEventItem[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [openBrief, setOpenBrief] = useState<string | null>(null);
  const requestedBrief = useSearchParams().get("brief");
  const scrolledTo = useRef<string | null>(null);

  // Opened from a "your brief is ready" notification.
  useEffect(() => {
    if (requestedBrief) setOpenBrief(requestedBrief);
  }, [requestedBrief]);

  useEffect(() => {
    if (!requestedBrief || !events || scrolledTo.current === requestedBrief) return;
    if (!events.some((event) => event.id === requestedBrief)) return;
    scrolledTo.current = requestedBrief;
    document.getElementById(`event-${requestedBrief}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [requestedBrief, events]);

  const load = useCallback(() => {
    api.listCalendarEvents(2).then(setEvents).catch(() => setEvents([]));
  }, []);

  useEffect(() => {
    api
      .getCalendar()
      .then((value) => {
        setState(value);
        if (value.connection) load();
      })
      .catch(() => setState({ configured: false, connection: null }));
  }, [load]);

  // Statuses change as meetings start; refresh once a minute while visible.
  useEffect(() => {
    if (!state?.connection) return;
    const handle = window.setInterval(() => document.visibilityState === "visible" && load(), 60_000);
    return () => window.clearInterval(handle);
  }, [state, load]);

  async function toggle(event: CalendarEventItem) {
    setBusyId(event.id);
    const next = !event.will_record;
    setEvents((current) => current?.map((item) => (item.id === event.id ? { ...item, will_record: next, record_override: next } : item)) ?? null);
    try {
      await api.updateCalendarEvent(event.id, next);
      load();
    } catch {
      setEvents((current) => current?.map((item) => (item.id === event.id ? event : item)) ?? null);
    } finally {
      setBusyId(null);
    }
  }

  if (!state || !state.configured) return null;

  if (!state.connection) {
    return (
      <section className="flex flex-col gap-3 rounded-xl border border-dashed p-4 sm:flex-row sm:items-center">
        <CalendarDays className="size-5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">Let the notetaker follow your calendar</p>
          <p className="text-sm text-muted-foreground">Link Google Calendar and it joins your meetings by itself, including calls with clients.</p>
        </div>
        <Link href="/settings#calendar" className="inline-flex h-8 shrink-0 items-center rounded-lg border px-3 text-sm font-medium hover:bg-muted">
          Link calendar
        </Link>
      </section>
    );
  }

  let lastDay = "";
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold">Coming up</h3>
        <Link href="/settings#calendar" className="flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground">
          Calendar settings <ArrowUpRight className="size-3.5" />
        </Link>
      </div>
      {state.connection.status === "error" && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          Your calendar stopped syncing. <Link href="/settings#calendar" className="font-medium underline">Reconnect it</Link> so the notetaker keeps joining.
        </p>
      )}
      {!events ? (
        <Skeleton className="h-32 w-full rounded-xl" />
      ) : events.length === 0 ? (
        <p className="rounded-xl border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No meetings in the next two days.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card">
          {events.map((event) => {
            const day = dayLabel(new Date(event.start_at));
            const header = day !== lastDay ? day : null;
            lastDay = day;
            const live = event.capture && (event.capture.active || event.capture.status === "stopped");
            const switchable = !event.unsupported_platform && !!event.meeting_url;
            return (
              <div key={event.id} id={`event-${event.id}`} className="border-b last:border-b-0">
                {header && <p className="border-b bg-muted/40 px-4 py-1.5 text-xs font-medium text-muted-foreground">{header}</p>}
                <div className="flex items-center gap-3 px-4 py-3">
                  <div className="w-24 shrink-0 text-xs text-muted-foreground tabular-nums">{timeRange(event)}</div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{event.title}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      {event.unsupported_platform ? (
                        <span>{event.unsupported_platform === "Microsoft Teams" ? "Microsoft Teams — paste the link in Send notetaker to record it" : `${event.unsupported_platform} — the notetaker joins Google Meet and Teams`}</span>
                      ) : live ? (
                        <Link href={`/meetings/live/${event.capture!.id}`} className="flex items-center gap-1 text-foreground hover:underline">
                          <span className={cn("size-1.5 rounded-full", event.capture?.status === "capturing" ? "bg-destructive" : "bg-warning")} />
                          {event.capture?.status_label}
                          {new Date(event.end_at).getTime() < Date.now() && <span className="text-muted-foreground"> · running over</span>}
                        </Link>
                      ) : event.capture?.status === "completed" && event.capture.meeting_id ? (
                        <Link href={`/meetings/${event.capture.meeting_id}`} className="text-primary hover:underline">Notes ready</Link>
                      ) : event.will_record ? (
                        <span>Notetaker joins at start</span>
                      ) : event.colleagues_on_it > 0 ? (
                        <span>Off for you — a colleague&apos;s calendar may still send it</span>
                      ) : (
                        <span>Notetaker won&apos;t join</span>
                      )}
                      {event.colleagues_on_it > 0 && (
                        <span className="flex items-center gap-1" title="Recorded once for everyone; all invitees get the notes">
                          <Users className="size-3" /> {event.colleagues_on_it} colleague{event.colleagues_on_it === 1 ? "" : "s"} also invited
                        </span>
                      )}
                    </p>
                  </div>
                  {event.brief && (
                    <button
                      type="button"
                      aria-expanded={openBrief === event.id}
                      aria-controls={`brief-${event.id}`}
                      onClick={() => setOpenBrief((current) => (current === event.id ? null : event.id))}
                      className="flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium text-primary hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      <NotebookPen className="size-3.5" />
                      <span className="hidden sm:inline">Brief</span>
                      <ChevronDown className={cn("size-3.5 transition-transform", openBrief === event.id && "rotate-180")} />
                    </button>
                  )}
                  {switchable && !live && (
                    <RecordSwitch on={event.will_record} busy={busyId === event.id} title={event.title} onToggle={() => void toggle(event)} />
                  )}
                </div>
                {event.brief && openBrief === event.id && (
                  <div id={`brief-${event.id}`} className="border-t bg-muted/30 px-4 py-3">
                    <BriefPanel brief={event.brief} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
