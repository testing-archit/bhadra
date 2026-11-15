"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, ChatSource, DirectoryUser, MeetingPrep } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { CitedMarkdown } from "@/components/cited-markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeft, CalendarDays, ListChecks, Loader2, NotebookPen, Scale, Search } from "lucide-react";

import { STATUS_LABELS } from "@/lib/labels";
import "../../../hackathon-intelligence.css";
const MAX_PEOPLE = 20;

/** A brief for an upcoming meeting, built only from earlier meetings you can
 * read that included the same colleagues — matched by account, never by a
 * shared name. */
export default function MeetingPrepPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [agenda, setAgenda] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prep, setPrep] = useState<MeetingPrep | null>(null);

  useEffect(() => {
    api.getDirectory().then(setDirectory).catch(() => setDirectory([]));
  }, []);

  const people = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return directory
      .filter((person) => person.email !== user?.email)
      .filter((person) => !needle || person.name.toLowerCase().includes(needle) || person.email.toLowerCase().includes(needle))
      .slice(0, 50);
  }, [directory, search, user?.email]);

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : current.length >= MAX_PEOPLE ? current : [...current, id],
    );
  }

  async function generate() {
    if (!selected.length) return;
    setBusy(true);
    setError(null);
    try {
      setPrep(await api.meetingPrep(selected, agenda.trim()));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The brief could not be prepared");
    } finally {
      setBusy(false);
    }
  }

  const sources: ChatSource[] = (prep?.meetings ?? []).map((meeting) => ({
    meeting_id: meeting.id,
    meeting_title: meeting.title,
    meeting_date: meeting.date,
    content_type: "meeting",
    tag: meeting.tag,
    segments: [],
  }));

  return (
    <div className="signal-intelligence-page signal-prep-page mx-auto flex max-w-3xl flex-col gap-6">
      <div className="signal-intelligence-hero">
        <Link href="/meetings" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground hover:underline">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to meetings
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Walk in with context</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick the people in your next sync. Wilco gathers earlier decisions, open work, and a cited briefing from meetings you can access.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="prep-search">Who will be there</Label>
            <div className="relative">
              <Search className="absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input id="prep-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a colleague" className="pl-8" />
            </div>
            <div className="grid grid-cols-1 max-h-56 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
              {people.length === 0 && <p className="p-2 text-xs text-muted-foreground">No colleagues found.</p>}
              {people.map((person) => (
                <label key={person.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted/50">
                  <Checkbox checked={selected.includes(person.id)} onCheckedChange={() => toggle(person.id)} />
                  <span className="min-w-0">
                    <span className="block truncate">{person.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{person.job_title || person.email}</span>
                  </span>
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{selected.length} selected · external guests aren&apos;t matched, since a name alone can&apos;t identify them.</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="prep-agenda">Agenda</Label>
            <Textarea id="prep-agenda" rows={4} value={agenda} onChange={(event) => setAgenda(event.target.value)} placeholder="Optional — what's this meeting about?" />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button onClick={() => void generate()} disabled={!selected.length || busy} className="self-start">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <NotebookPen className="h-4 w-4" />}
            {busy ? "Preparing…" : "Prepare brief"}
          </Button>
        </CardContent>
      </Card>

      {prep && (
        <>
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><NotebookPen className="h-4 w-4 text-primary" /> Brief</CardTitle></CardHeader>
            <CardContent>
              {prep.brief ? (
                <CitedMarkdown
                  content={prep.brief}
                  sources={sources}
                  onCite={(citation) => citation.source.meeting_id && router.push(`/meetings/${citation.source.meeting_id}`)}
                />
              ) : (
                <p className="text-sm text-muted-foreground">{prep.brief_error ?? "No brief was produced."}</p>
              )}
            </CardContent>
          </Card>

          {prep.meetings.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CalendarDays className="h-4 w-4 text-primary" /> Earlier meetings</CardTitle></CardHeader>
                <CardContent className="flex flex-col gap-1.5">
                  {prep.meetings.map((meeting) => (
                    <Link key={meeting.id} href={`/meetings/${meeting.id}`} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted/50">
                      <span className="min-w-0 truncate"><span className="mr-1.5 font-mono text-xs text-muted-foreground">{meeting.tag}</span>{meeting.title}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{new Date(meeting.date).toLocaleDateString()}</span>
                    </Link>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><ListChecks className="h-4 w-4 text-primary" /> Open tasks</CardTitle></CardHeader>
                <CardContent className="flex flex-col gap-2">
                  {prep.open_tasks.length === 0 && <p className="text-sm text-muted-foreground">Nothing open from these meetings.</p>}
                  {prep.open_tasks.map((task) => (
                    <div key={task.id} className="text-sm">
                      <p>{task.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {task.owner || "Owner not stated"} · {(STATUS_LABELS[task.status] ?? task.status)}
                        {task.deadline && ` · due ${task.deadline}`}
                        {task.meeting_tag && ` · ${task.meeting_tag}`}
                      </p>
                    </div>
                  ))}
                </CardContent>
              </Card>
              {prep.decisions.length > 0 && (
                <Card className="md:col-span-2">
                  <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Scale className="h-4 w-4 text-primary" /> Recent decisions</CardTitle></CardHeader>
                  <CardContent className="flex flex-col gap-1.5">
                    {prep.decisions.map((decision) => (
                      <p key={decision.id} className="text-sm">
                        <span className="mr-1.5 font-mono text-xs text-muted-foreground">{decision.meeting_tag}</span>
                        {decision.decision}
                      </p>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
