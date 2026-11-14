"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Link2,
  Video,
} from "lucide-react";
import { api, type CalendarSchedule, type ScheduleEvent } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { RecordSwitch } from "@/components/record-switch";
import { MeetingPeople } from "@/components/meeting-people";
import { useShell } from "@/components/shell/shell-context";

type Range = "live" | "upcoming" | "past";
const dateKey = (date: Date) => date.toDateString();
const time = (value: string) =>
  new Date(value).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });

export function MeetingAgenda() {
  const [schedule, setSchedule] = useState<CalendarSchedule | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<Range>("upcoming");
  const [weekOffset, setWeekOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setSchedule(await api.getCalendarSchedule(14, 14));
      setError(false);
    } catch {
      setError(true);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7) + weekOffset * 7);
  monday.setHours(0, 0, 0, 0);
  const days = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(monday);
    day.setDate(monday.getDate() + index);
    return day;
  });
  const events = (schedule?.events ?? []).filter(
    (event) =>
      event.when === range &&
      (!selected || dateKey(new Date(event.start_at)) === selected),
  );
  if (range === "past") events.reverse();
  return (
    <section className="agenda-panel" aria-labelledby="agenda-heading">
      <div className="section-heading">
        <h2 id="agenda-heading">Your schedule</h2>
        <Link href="/meetings?view=calendar" className="text-xs text-primary">
          View all
        </Link>
      </div>
      <Tabs
        value={range}
        onValueChange={(value) => {
          setRange(value as Range);
          setSelected(null);
        }}
      >
        <TabsList className="agenda-tabs" aria-label="Schedule range">
          <TabsTrigger value="live">Ongoing</TabsTrigger>
          <TabsTrigger value="upcoming">Upcoming</TabsTrigger>
          <TabsTrigger value="past">History</TabsTrigger>
        </TabsList>
        <div className="agenda-month">
          <button
            type="button"
            className="calendar-arrow"
            aria-label="Previous week"
            disabled={weekOffset <= -2}
            onClick={() => {
              setWeekOffset((old) => old - 1);
              setSelected(null);
            }}
          >
            <ChevronLeft className="size-4" />
          </button>
          <span>
            {monday.toLocaleDateString(undefined, {
              month: "long",
              year: "numeric",
            })}
          </span>
          <button
            type="button"
            className="calendar-arrow"
            aria-label="Next week"
            disabled={weekOffset >= 2}
            onClick={() => {
              setWeekOffset((old) => old + 1);
              setSelected(null);
            }}
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
        <div className="week-strip" role="group" aria-label="Filter by day">
          {days.map((day) => {
            const key = dateKey(day);
            const hasMeeting = schedule?.events.some(
              (event) => dateKey(new Date(event.start_at)) === key,
            );
            return (
              <button
                type="button"
                key={key}
                className="week-day"
                aria-label={day.toLocaleDateString(undefined, {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                })}
                aria-pressed={selected === key}
                data-today={key === dateKey(today)}
                onClick={() => setSelected((old) => (old === key ? null : key))}
              >
                <span>
                  {day.toLocaleDateString(undefined, { weekday: "short" })}
                </span>
                <strong>{day.getDate()}</strong>
                <i data-event={Boolean(hasMeeting)} aria-hidden="true" />
              </button>
            );
          })}
        </div>
        {selected && (
          <div className="mb-3 flex justify-end">
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-xs text-primary"
            >
              Show all days
            </button>
          </div>
        )}
        {[range].map((value) => (
          <TabsContent value={value} key={value} className="agenda-events">
            {error ? (
              <div className="agenda-empty" role="alert">
                <p>Your calendar couldn&apos;t load.</p>
                <button
                  type="button"
                  onClick={() => void load()}
                  className="text-primary"
                >
                  Try again
                </button>
              </div>
            ) : !schedule ? (
              <Skeleton className="h-44 rounded-2xl" />
            ) : !schedule.connection ? (
              <div className="agenda-empty">
                <span className="calendar-illustration" aria-hidden="true">
                  <CalendarDays />
                </span>
                <h3>Make room for what&apos;s next.</h3>
                <p>Connect your calendar to see upcoming meetings here.</p>
                <Link href="/settings#calendar" className="violet-button">
                  Connect calendar
                </Link>
                <Link
                  href="/meetings"
                  className="text-xs text-muted-foreground"
                >
                  Browse recorded meetings
                </Link>
              </div>
            ) : events.length ? (
              events
                .slice(0, 5)
                .map((event) => (
                  <AgendaCard key={event.id} event={event} onChanged={load} />
                ))
            ) : (
              <div className="agenda-empty">
                <CalendarDays
                  className="size-7 text-primary"
                  aria-hidden="true"
                />
                <h3>
                  {selected
                    ? "Nothing on this day."
                    : value === "live"
                      ? "No meeting in progress."
                      : value === "upcoming"
                        ? "A little room in your week."
                        : "No past meetings here yet."}
                </h3>
                <p>
                  {selected
                    ? "Choose another day or show all days."
                    : "Your calendar meetings will appear here."}
                </p>
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}

function AgendaCard({
  event,
  onChanged,
}: {
  event: ScheduleEvent;
  onChanged: () => Promise<void>;
}) {
  const { openNotetaker } = useShell();
  const [copied, setCopied] = useState(false);
  const [recordBusy, setRecordBusy] = useState(false);
  const [recordError, setRecordError] = useState(false);
  async function toggleRecording() {
    setRecordBusy(true);
    setRecordError(false);
    try {
      await api.updateCalendarEvent(event.id, !event.will_record);
      await onChanged();
    } catch {
      setRecordError(true);
    } finally {
      setRecordBusy(false);
    }
  }
  const [copyError, setCopyError] = useState(false);
  async function copy() {
    if (!event.meeting_url) return;
    try {
      await navigator.clipboard.writeText(event.meeting_url);
      setCopied(true);
      setCopyError(false);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyError(true);
    }
  }
  return (
    <article className="schedule-meeting-card">
      <div className="meeting-card-meta">
        <span className="time-chip">
          <Clock3 className="size-3" aria-hidden="true" />
          {time(event.start_at)}
        </span>
        <span>
          {new Date(event.start_at).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
          })}
        </span>
        {event.capture?.active && (
          <span className="ml-auto text-primary">
            {event.capture.status_label}
          </span>
        )}
      </div>
      <h3>{event.title}</h3>
      {event.meeting_url && (
        <div className="meeting-url">
          <Video
            className="size-3.5 shrink-0 text-primary"
            aria-hidden="true"
          />
          <span>{event.meeting_url.replace(/^https?:\/\//, "")}</span>
          <button
            type="button"
            onClick={() => void copy()}
            aria-label={copied ? "Meeting link copied" : "Copy meeting link"}
            className="calendar-arrow"
          >
            {copied ? (
              <Check className="size-3.5" />
            ) : (
              <Copy className="size-3.5" />
            )}
          </button>
        </div>
      )}
      {copyError && (
        <p className="text-xs text-destructive" role="alert">
          Copy the meeting link from its text above.
        </p>
      )}
      <div className="meeting-card-bottom">
        <MeetingPeople
          names={event.invitee_names}
          total={event.invitee_count}
        />
        {event.notes ? (
          <Link href={`/meetings/${event.notes.id}`} className="violet-outline">
            Open notes
          </Link>
        ) : event.meeting_url ? (
          <a
            href={event.meeting_url}
            target="_blank"
            rel="noopener noreferrer"
            className="violet-outline"
          >
            Join meeting
          </a>
        ) : (
          <span className="text-xs text-muted-foreground">No meeting link</span>
        )}
      </div>
      {event.when === "upcoming" &&
        event.platform === "Google Meet" &&
        event.meeting_url && (
          <div className="mt-4 flex items-center justify-between gap-3 border-t pt-3 text-xs text-muted-foreground">
            <span>Auto-invite Wilco</span>
            <RecordSwitch
              on={event.will_record}
              busy={recordBusy}
              title={event.title}
              onToggle={() => void toggleRecording()}
            />
          </div>
        )}
      {recordError && (
        <p className="mt-2 text-xs text-destructive" role="alert">
          Couldn't change recording. Try again.
        </p>
      )}
      {event.when !== "past" &&
        event.meeting_url &&
        !event.capture?.active &&
        !event.unsupported_platform && (
          <button
            type="button"
            onClick={() => openNotetaker(event.meeting_url!)}
            className="agenda-invite"
          >
            <Link2 className="size-3.5" aria-hidden="true" />
            Invite Wilco
          </button>
        )}
    </article>
  );
}
