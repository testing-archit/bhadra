"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Bot, CalendarDays, Clock, Loader2, Plus, Search, SlidersHorizontal, Users, Video, X } from "lucide-react";
import { api, ApiError, type DirectoryUser, type MeetingSummary } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { useShell } from "@/components/shell/shell-context";
import { cn } from "@/lib/utils";
import { SOURCE_LABELS } from "@/lib/labels";
import { CalendarSchedule } from "@/components/calendar-schedule";


const selectClass = "h-8 rounded-lg border bg-background px-2.5 text-sm text-foreground";

function dayBucket(date: Date): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(date);
  day.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - day.getTime()) / 86_400_000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return "Earlier this week";
  if (day.getFullYear() === today.getFullYear()) return day.toLocaleDateString(undefined, { month: "long" });
  return day.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

export default function MeetingsPage() {
  const { openNotetaker } = useShell();
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MeetingSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);
  const [attendeeId, setAttendeeId] = useState("");
  const [source, setSource] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  // "recorded": meetings in Wilco; "calendar": the person's Google Calendar.
  const [view, setView] = useState<"recorded" | "calendar">("recorded");

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("view") === "calendar") setView("calendar");
  }, []);

  function chooseView(next: "recorded" | "calendar") {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "calendar") url.searchParams.set("view", "calendar");
    else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
  }
  const filters = useMemo(
    () => ({ source: source || undefined, dateFrom: dateFrom || undefined, dateTo: dateTo || undefined }),
    [source, dateFrom, dateTo],
  );
  const activeFilterCount = [attendeeId, source, dateFrom, dateTo].filter(Boolean).length;

  useEffect(() => {
    api
      .listMeetings(undefined, undefined, attendeeId || undefined, filters)
      .then(setMeetings)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Meetings could not be loaded."));
  }, [attendeeId, filters]);

  useEffect(() => {
    api.getDirectory().then(setDirectory).catch(() => setDirectory([]));
    // The extension's address-bar search ("mem meetings: …") lands here.
    const handed = new URLSearchParams(window.location.search).get("q");
    if (handed) setQuery(handed);
  }, []);

  // Server-side search covers titles, summaries and full transcripts.
  useEffect(() => {
    const q = query.trim();
    if (!q) return;
    const handle = window.setTimeout(() => {
      setSearching(true);
      api
        .listMeetings(q, undefined, attendeeId || undefined, filters)
        .then(setSearchResults)
        .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Search failed."))
        .finally(() => setSearching(false));
    }, 300);
    return () => window.clearTimeout(handle);
  }, [query, attendeeId, filters]);

  const displayed = query.trim() ? searchResults : meetings;

  const groups = useMemo(() => {
    if (!displayed) return [];
    const out: { label: string; items: MeetingSummary[] }[] = [];
    for (const meeting of displayed) {
      const label = dayBucket(new Date(meeting.date));
      const last = out[out.length - 1];
      if (last?.label === label) last.items.push(meeting);
      else out.push({ label, items: [meeting] });
    }
    return out;
  }, [displayed]);

  function clearFilters() {
    setAttendeeId("");
    setSource("");
    setDateFrom("");
    setDateTo("");
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Meetings"
        description="Every meeting your team has captured, with its transcript, notes and follow-ups."
        actions={
          <>
            <Button variant="outline" onClick={() => openNotetaker()}>
              <Bot /> Send notetaker
            </Button>
            <Link href="/meetings/new" className={buttonVariants()}>
              <Plus /> Add meeting
            </Link>
          </>
        }
      />

      <NotetakerActivity />

      <div className="flex gap-1 self-start rounded-lg bg-muted p-0.5" role="tablist" aria-label="Meetings view">
        {([
          ["recorded", "Recorded", Video],
          ["calendar", "Calendar", CalendarDays],
        ] as const).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={view === value}
            onClick={() => chooseView(value)}
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-md px-3 text-sm text-muted-foreground",
              view === value && "bg-background font-medium text-foreground shadow-sm",
            )}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      {view === "calendar" ? <CalendarSchedule /> : <>
      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            {searching ? (
              <Loader2 className="absolute top-1/2 left-3 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />
            ) : (
              <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            )}
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search titles, summaries and transcripts"
              className="h-9 pl-9"
              aria-label="Search meetings"
            />
          </div>
          <Button
            variant={showFilters || activeFilterCount ? "secondary" : "outline"}
            className="h-9"
            onClick={() => setShowFilters((value) => !value)}
            aria-expanded={showFilters}
          >
            <SlidersHorizontal /> Filters{activeFilterCount ? ` (${activeFilterCount})` : ""}
          </Button>
        </div>
        {showFilters && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-3">
            {directory.length > 1 && (
              <select value={attendeeId} onChange={(event) => setAttendeeId(event.target.value)} aria-label="Attendee" className={selectClass}>
                <option value="">Anyone attended</option>
                {directory.map((person) => (
                  <option key={person.id} value={person.id}>With {person.name}</option>
                ))}
              </select>
            )}
            <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Source" className={selectClass}>
              <option value="">Any source</option>
              {Object.entries(SOURCE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} aria-label="From date" className="w-38" />
              to
              <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} aria-label="To date" className="w-38" />
            </div>
            {activeFilterCount > 0 && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="ml-auto">
                <X /> Clear filters
              </Button>
            )}
          </div>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!displayed && !error && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((index) => <Skeleton key={index} className="h-20 w-full rounded-xl" />)}
        </div>
      )}

      {displayed && displayed.length === 0 && !searching && (
        meetings?.length === 0 && !activeFilterCount ? (
          <EmptyState
            icon={Video}
            title="No meetings yet"
            description="Send the notetaker into your next Google Meet or Teams call, or add a recording you already have."
            action={<Button onClick={() => openNotetaker()}><Bot /> Send notetaker</Button>}
          />
        ) : (
          <EmptyState icon={Search} title="No meetings match" description="Try a different search or clear the filters." />
        )
      )}

      {groups.map((group) => (
        <section key={group.label} className="flex flex-col gap-1">
          <h2 className="px-1 pb-1 text-sm font-medium text-muted-foreground">{group.label}</h2>
          <div className="overflow-hidden rounded-xl border bg-card">
            {group.items.map((meeting) => <MeetingRow key={meeting.id} meeting={meeting} />)}
          </div>
        </section>
      ))}
      </>}
    </div>
  );
}

function MeetingRow({ meeting }: { meeting: MeetingSummary }) {
  const date = new Date(meeting.date);
  const noItems = meeting.task_count === 0 && meeting.decision_count === 0;
  return (
    <Link
      href={`/meetings/${meeting.id}`}
      className="group flex gap-4 border-b px-4 py-3.5 outline-none transition-colors last:border-b-0 hover:bg-muted/50 focus-visible:bg-muted/60"
    >
      <div className="hidden w-14 shrink-0 flex-col items-center justify-center rounded-lg bg-muted py-1.5 text-center sm:flex">
        <span className="text-xs text-muted-foreground">{date.toLocaleDateString(undefined, { month: "short" })}</span>
        <span className="text-lg leading-none font-semibold tabular-nums">{date.getDate()}</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <p className="truncate font-medium group-hover:text-primary">{meeting.title}</p>
          <div className="flex shrink-0 items-center gap-1.5">
            {meeting.processing_state === "processing" && (
              <Badge variant="outline" className="gap-1"><Loader2 className="size-3 animate-spin" /> Processing</Badge>
            )}
            {meeting.processing_state === "attention" && (
              <Badge variant="outline" className="gap-1 border-warning/50 text-warning"><AlertTriangle className="size-3" /> Needs attention</Badge>
            )}
            {meeting.processing_state !== "processing" && !noItems && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {meeting.task_count} task{meeting.task_count === 1 ? "" : "s"}, {meeting.decision_count} decision{meeting.decision_count === 1 ? "" : "s"}
              </span>
            )}
          </div>
        </div>
        {meeting.summary && <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">{meeting.summary}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Clock className="size-3.5" />
            {date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}
            {meeting.duration_minutes ? `, ${meeting.duration_minutes} min` : ""}
          </span>
          {meeting.attendees.length > 0 && (
            <span className="flex min-w-0 items-center gap-1">
              <Users className="size-3.5 shrink-0" />
              <span className="truncate">
                {meeting.attendees.slice(0, 3).map((person) => person.name).join(", ")}
                {meeting.attendees.length > 3 && ` +${meeting.attendees.length - 3}`}
              </span>
            </span>
          )}
          {meeting.source && <span>{SOURCE_LABELS[meeting.source] ?? meeting.source}</span>}
          {meeting.projects.map((project) => (
            <Badge key={project.id} variant="outline" className="h-5 text-[11px]">{project.name}</Badge>
          ))}
        </div>
      </div>
    </Link>
  );
}

/** Recent notetaker requests that didn't become a meeting — denied entry,
 * timed out, failed — so people find out why a meeting is missing. */
function NotetakerActivity() {
  const { captures } = useShell();
  const dayAgo = Date.now() - 86_400_000;
  const problems = captures.filter(
    (request) =>
      ["denied", "timed_out", "failed"].includes(request.status) &&
      request.updated_at &&
      new Date(request.updated_at).getTime() > dayAgo,
  );
  if (!problems.length) return null;
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-warning/40 bg-warning/5 p-3">
      {problems.slice(0, 3).map((request) => (
        <div key={request.id} className={cn("flex items-start gap-2.5 text-sm")}>
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <p className="min-w-0">
            <span className="font-medium">{request.title || request.meeting_code}</span>
            <span className="text-muted-foreground">: {request.status_label}{request.status_detail ? `. ${request.status_detail}` : ""}</span>
          </p>
        </div>
      ))}
    </div>
  );
}
