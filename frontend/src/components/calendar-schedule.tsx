"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, CalendarDays, FileText, NotebookPen, Radio, Repeat, Users, Video } from "lucide-react";
import { api, type CalendarSchedule as Schedule, type ScheduleEvent } from "@/lib/api";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RecordSwitch } from "@/components/record-switch";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
type Range = "upcoming" | "past";

function dayLabel(date: Date) {
  const today = new Date();
  const other = new Date(today);
  if (date.toDateString() === today.toDateString()) return "Today";
  other.setDate(today.getDate() + 1);
  if (date.toDateString() === other.toDateString()) return "Tomorrow";
  other.setDate(today.getDate() - 1);
  if (date.toDateString() === other.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

const time = (value: string) => new Date(value).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

/** The person's Google Calendar inside Wilco: what's coming up (with the
 * notetaker switch) and what already happened (with its notes, when it was
 * recorded). Read-only — Wilco never changes the calendar. */
export function CalendarSchedule() {
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [range, setRange] = useState<Range>("upcoming");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getCalendarSchedule(14, 7)
      .then((value) => {
        setSchedule(value);
        setError(null);
      })
      .catch(() => setError("Your calendar couldn't be loaded."));
  }, []);

  useEffect(() => {
    api.getCalendar().then((state) => setConfigured(state.configured)).catch(() => setConfigured(false));
    load();
    const handle = window.setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => window.clearInterval(handle);
  }, [load]);

  async function toggle(event: ScheduleEvent) {
    setBusyId(event.id);
    const next = !event.will_record;
    setSchedule((current) => current && { ...current, events: current.events.map((e) => (e.id === event.id ? { ...e, will_record: next } : e)) });
    try {
      await api.updateCalendarEvent(event.id, next);
      load();
    } catch {
      setSchedule((current) => current && { ...current, events: current.events.map((e) => (e.id === event.id ? event : e)) });
    } finally {
      setBusyId(null);
    }
  }

  if (!schedule && !error) return <Skeleton className="h-72 w-full rounded-xl" />;

  const connection = schedule?.connection ?? null;
  if (!connection) {
    return (
      <section className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center">
        <CalendarDays className="size-6 text-primary" />
        <div>
          <p className="font-medium">See your Google Calendar here</p>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            {configured === false
              ? "Calendar linking isn't switched on for this workspace yet. An admin needs to add the Google OAuth client."
              : "Link your calendar to see past and upcoming meetings next to their notes — and let the notetaker join them by itself."}
          </p>
        </div>
        {configured !== false && (
          <Link href="/settings#calendar" className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            <CalendarDays className="size-4" /> Link Google Calendar
          </Link>
        )}
      </section>
    );
  }

  const events = (schedule?.events ?? []).filter((e) => (range === "past" ? e.when === "past" : e.when !== "past"));
  if (range === "past") events.reverse();
  const groups: { label: string; items: ScheduleEvent[] }[] = [];
  for (const event of events) {
    const label = dayLabel(new Date(event.start_at));
    if (groups.at(-1)?.label !== label) groups.push({ label, items: [] });
    groups.at(-1)!.items.push(event);
  }
  const recordedPast = (schedule?.events ?? []).filter((e) => e.when === "past" && e.notes).length;
  const totalPast = (schedule?.events ?? []).filter((e) => e.when === "past").length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/30 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-background shadow-sm">
            <CalendarDays className="size-4 text-primary" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-medium">From your Google Calendar</p>
            <p className="truncate text-xs text-muted-foreground">
              {connection.google_email}
              {connection.status === "error"
                ? " · not syncing — reconnect in Settings"
                : connection.live_updates
                  ? " · updates live"
                  : connection.last_synced_at
                    ? ` · synced ${time(connection.last_synced_at)}`
                    : " · syncing…"}
              {" · read-only"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-0.5 rounded-lg bg-muted p-0.5" role="tablist" aria-label="Which meetings">
            {(["upcoming", "past"] as Range[]).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={range === value}
                onClick={() => setRange(value)}
                className={cn("h-7 rounded-md px-3 text-sm text-muted-foreground", range === value && "bg-background font-medium text-foreground shadow-sm")}
              >
                {value === "upcoming" ? "Upcoming" : "Past"}
              </button>
            ))}
          </div>
          <Link href="/settings#calendar" className="hidden items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground sm:flex">
            Settings <ArrowUpRight className="size-3.5" />
          </Link>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {range === "past" && totalPast > 0 && (
        <p className="px-1 text-xs text-muted-foreground">
          {recordedPast} of {totalPast} meetings in the last two weeks have notes in Wilco.
        </p>
      )}

      {groups.length === 0 ? (
        <p className="rounded-xl border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
          {range === "upcoming" ? "Nothing on your calendar for the next week." : "No meetings on your calendar in the last two weeks."}
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.label} className="flex flex-col gap-1">
            <h2 className="px-1 pb-1 text-sm font-medium text-muted-foreground">{group.label}</h2>
            <div className="overflow-hidden rounded-xl border bg-card">
              {group.items.map((event) => (
                <EventRow key={event.id} event={event} busy={busyId === event.id} onToggle={() => void toggle(event)} />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function EventRow({ event, busy, onToggle }: { event: ScheduleEvent; busy: boolean; onToggle: () => void }) {
  const recording = event.capture?.status === "capturing";
  const canRecord = event.platform === "Google Meet" && !!event.meeting_url;
  const others = event.invitee_names.slice(0, 3).join(", ") + (event.invitee_count > 3 ? ` +${event.invitee_count - 3}` : "");

  let status: React.ReactNode;
  if (event.notes) {
    status = (
      <Link href={`/meetings/${event.notes.id}`} className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/15">
        <FileText className="size-3.5" /> Notes
      </Link>
    );
  } else if (event.when === "live") {
    status = event.capture ? (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium">
        <span className={cn("size-1.5 rounded-full", recording ? "bg-destructive" : "bg-warning")} />
        {event.capture.status_label}
      </span>
    ) : (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Radio className="size-3.5" /> On now</span>
    );
  } else if (event.when === "past") {
    const why = event.capture && !event.capture.active && event.capture.status !== "stopped" ? event.capture.status_label : undefined;
    status = (
      <span className={cn("text-xs text-muted-foreground", why && "underline decoration-dotted underline-offset-2")} title={why}>
        {event.capture?.status === "stopped" ? "Processing notes…" : "Not recorded"}
      </span>
    );
  } else if (canRecord) {
    status = <RecordSwitch on={event.will_record} busy={busy} title={event.title} onToggle={onToggle} />;
  } else {
    status = <span className="text-xs text-muted-foreground">Notetaker can&apos;t join</span>;
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3 last:border-b-0", event.when === "live" && "bg-primary/5")}>
      <div className="flex w-14 shrink-0 flex-col text-xs text-muted-foreground tabular-nums sm:w-24 sm:flex-row sm:gap-1">
        <span>{time(event.start_at)}</span>
        <span>– {time(event.end_at)}</span>
      </div>
      <div className="min-w-0 flex-1 basis-40">
        <p className="flex items-center gap-1.5 truncate text-sm font-medium">
          <span className="truncate">{event.title}</span>
          {event.recurring && <Repeat className="size-3 shrink-0 text-muted-foreground" aria-label="Recurring" />}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          {event.platform && (
            <span className="inline-flex items-center gap-1"><Video className="size-3" /> {event.platform}</span>
          )}
          {event.invitee_count > 0 && (
            <span className="inline-flex min-w-0 items-center gap-1"><Users className="size-3 shrink-0" /> <span className="truncate">{others}</span></span>
          )}
          {event.is_organizer && <span>You organise</span>}
          {event.brief_ready && event.when !== "past" && (
            <Link href={`/dashboard?brief=${event.id}`} className="inline-flex items-center gap-1 text-primary hover:underline"><NotebookPen className="size-3" /> Brief</Link>
          )}
        </p>
      </div>
      <div className="ml-[4.25rem] flex shrink-0 items-center gap-2 sm:ml-0">
        {event.when !== "past" && event.meeting_url && (
          <a href={event.meeting_url} target="_blank" rel="noopener noreferrer" className={cn(buttonVariants({ size: "sm", variant: "outline" }), "hidden sm:inline-flex")}>
            Join
          </a>
        )}
        {status}
      </div>
    </div>
  );
}
