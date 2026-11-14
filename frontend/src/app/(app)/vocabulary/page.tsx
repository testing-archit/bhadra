"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Captions, Check, Loader2, Plus, Search, Sparkles, Trash2, UserPlus, Users, X } from "lucide-react";
import { api, ApiError, type VocabularyEntry, type VocabularyPerson, type VocabularySuggestion } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

/** The names and terms transcription gets wrong, shared by the company.
 * Corrections fix every new transcript and the notes written from it;
 * keywords, teammates' names (the meeting's people first) and the right
 * spelling of every correction are sent to Prisma so they're heard right.
 * Fixing a misheard name in any meeting adds it here automatically, and
 * Charcha suggests ones it noticed itself. */
export default function VocabularyPage() {
  const { user } = useAuth();
  const [entries, setEntries] = useState<VocabularyEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [heardAs, setHeardAs] = useState("");
  const [fixPast, setFixPast] = useState(true);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [people, setPeople] = useState<VocabularyPerson[] | null>(null);
  const [suggestions, setSuggestions] = useState<VocabularySuggestion[]>([]);

  function reload() {
    api.listVocabulary().then(setEntries).catch((cause) => setError(cause instanceof ApiError ? cause.message : "Vocabulary couldn't be loaded"));
    api.listVocabularyPeople().then(setPeople).catch(() => setPeople([]));
    api.listVocabularySuggestions().then(setSuggestions).catch(() => setSuggestions([]));
  }

  useEffect(reload, []);

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!term.trim()) return;
    const variants = heardAs.split(",").map((value) => value.trim()).filter(Boolean);
    setAdding(true);
    setError(null);
    setNotice(null);
    try {
      const added = await api.addVocabulary({ term: term.trim(), heard_as: variants, fix_past: fixPast });
      setEntries((current) => [...added, ...(current ?? []).filter((entry) => !added.some((item) => item.id === entry.id))]);
      setNotice(
        variants.length
          ? `From now on "${variants.join('", "')}" becomes "${term.trim()}" in every new transcript${fixPast ? ". Past meetings are being fixed in the background." : "."}`
          : `"${term.trim()}" is now listened for in every recording.`,
      );
      setTerm("");
      setHeardAs("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That couldn't be added");
    } finally {
      setAdding(false);
    }
  }

  async function setEnabled(entry: VocabularyEntry, enabled: boolean) {
    setBusyId(entry.id);
    try {
      const updated = await api.updateVocabulary(entry.id, { enabled });
      setEntries((current) => current?.map((item) => (item.id === entry.id ? { ...item, ...updated, created_by: item.created_by, source_meeting_title: item.source_meeting_title } : item)) ?? null);
      setPeople((current) => current?.map((person) => ({ ...person, heard_as: person.heard_as.map((rule) => (rule.id === entry.id ? { ...rule, enabled } : rule)) })) ?? null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That change wasn't saved");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(entry: VocabularyEntry) {
    setBusyId(entry.id);
    try {
      await api.deleteVocabulary(entry.id);
      setEntries((current) => current?.filter((item) => item.id !== entry.id) ?? null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That couldn't be deleted");
    } finally {
      setBusyId(null);
    }
  }

  const needle = query.trim().toLowerCase();
  const visible = useMemo(
    () => (entries ?? []).filter((entry) => !needle || `${entry.heard_as ?? ""} ${entry.term}`.toLowerCase().includes(needle)),
    [entries, needle],
  );
  const visiblePeople = (people ?? []).filter(
    (person) => !needle || `${person.name} ${person.heard_as.map((rule) => rule.heard_as).join(" ")}`.toLowerCase().includes(needle),
  );
  const corrections = visible.filter((entry) => entry.kind === "correction");
  const keywords = visible.filter((entry) => entry.kind === "keyword");
  const canDelete = (entry: VocabularyEntry) => !!user && (user.is_admin || entry.created_by_id === user.id);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Vocabulary"
        description="Names and terms that transcription gets wrong. Charcha fixes them in every new meeting and its notes, and tells the transcriber to listen for them, starting with the people invited to the meeting. When you correct a misheard name in a meeting, it's learned here automatically."
      />

      {suggestions.length > 0 && (
        <SuggestionsCard
          suggestions={suggestions}
          onDecided={(id, accepted) => {
            setSuggestions((current) => current.filter((item) => item.id !== id));
            if (accepted) reload();
          }}
          onError={setError}
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add a name or term</CardTitle>
          <CardDescription>
            Leave “Heard as” empty to add a keyword, such as a teammate&apos;s or client&apos;s name, so it&apos;s recognised. Fill it in to fix a known mishearing, for example “Sky Tech, Skytech” → “Sky Lattice”.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={add} className="flex flex-col gap-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="vocab-heard-as">Heard as (optional, comma-separated)</Label>
                <Input id="vocab-heard-as" value={heardAs} onChange={(event) => setHeardAs(event.target.value)} placeholder="Sky Tech, Skytech" maxLength={400} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="vocab-term">Correct spelling</Label>
                <Input id="vocab-term" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Sky Lattice" maxLength={80} required />
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <Checkbox checked={fixPast} onCheckedChange={(checked) => setFixPast(checked === true)} disabled={!heardAs.trim()} />
                Also fix meetings that already have the wrong spelling
              </label>
              <Button type="submit" size="sm" disabled={adding || !term.trim()}>
                {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Add
              </Button>
            </div>
            {notice && <p className="text-sm text-muted-foreground">{notice}</p>}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </form>
        </CardContent>
      </Card>

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search vocabulary" className="pl-8" aria-label="Search vocabulary" />
      </div>

      {people === null ? <Skeleton className="h-40 w-full" /> : <TeammatesCard people={visiblePeople} total={people.length} searching={!!needle} onChanged={reload} onToggle={(id, enabled) => {
        const entry = entries?.find((item) => item.id === id);
        if (entry) void setEnabled(entry, enabled);
      }} />}

      {entries === null ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Corrections ({corrections.length})</CardTitle>
              <CardDescription>Applied to every new transcript. Switch one off if it ever replaces something it shouldn&apos;t.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col divide-y">
              {corrections.length === 0 && <p className="py-2 text-sm text-muted-foreground">No corrections yet. Fix a misheard name in any meeting, or add one above.</p>}
              {corrections.map((entry) => (
                <div key={entry.id} className={`flex flex-wrap items-center gap-3 py-3 ${entry.enabled ? "" : "opacity-60"}`}>
                  <Checkbox
                    checked={entry.enabled}
                    disabled={busyId === entry.id}
                    onCheckedChange={(checked) => void setEnabled(entry, checked === true)}
                    aria-label={entry.enabled ? `Switch off ${entry.heard_as} → ${entry.term}` : `Switch on ${entry.heard_as} → ${entry.term}`}
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <p className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="text-muted-foreground line-through decoration-muted-foreground/60">{entry.heard_as}</span>
                      <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">{entry.term}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      <EntryOrigin entry={entry} />
                      {entry.times_applied > 0 && ` · fixed ${entry.times_applied} time${entry.times_applied === 1 ? "" : "s"} in new transcripts`}
                    </p>
                  </div>
                  <SourceBadge entry={entry} />
                  {canDelete(entry) && (
                    <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" disabled={busyId === entry.id} onClick={() => void remove(entry)} aria-label={`Delete ${entry.heard_as} → ${entry.term}`}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Keywords ({keywords.length})</CardTitle>
              <CardDescription>Names and terms the transcriber is told to listen for in every recording. Ones marked “Auto” were picked up from projects, Jira and recurring meeting titles; switch one off and it stays off.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {keywords.length === 0 && <p className="text-sm text-muted-foreground">No keywords yet.</p>}
              {keywords.map((entry) => (
                <span key={entry.id} className={`flex items-center gap-1.5 rounded-md border py-1 pl-2 pr-1 text-sm ${entry.enabled ? "" : "opacity-60"}`}>
                  <Checkbox checked={entry.enabled} disabled={busyId === entry.id} onCheckedChange={(checked) => void setEnabled(entry, checked === true)} aria-label={entry.enabled ? `Switch off ${entry.term}` : `Switch on ${entry.term}`} />
                  {entry.term}
                  {entry.source === "auto" && (
                    <span className="text-xs text-muted-foreground" title={entry.note ?? undefined}>
                      · Auto{entry.note ? `, ${entry.note.toLowerCase()}` : ""}
                    </span>
                  )}
                  {canDelete(entry) && (
                    <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" disabled={busyId === entry.id} onClick={() => void remove(entry)} aria-label={`Delete ${entry.term}`}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </span>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function SourceBadge({ entry }: { entry: VocabularyEntry }) {
  if (entry.source === "learned") return <Badge variant="secondary"><Sparkles className="h-3 w-3" /> Learned</Badge>;
  if (entry.source === "suggested") return <Badge variant="secondary"><Sparkles className="h-3 w-3" /> Suggested</Badge>;
  return <Badge variant="outline">Added</Badge>;
}

function EntryOrigin({ entry }: { entry: VocabularyEntry }) {
  if (entry.source === "suggested") {
    return (
      <>
        {entry.note ?? "Suggested by Charcha"}
        {entry.source_meeting_id && (
          <>
            {" · first noticed in "}
            <Link href={`/meetings/${entry.source_meeting_id}`} className="underline underline-offset-2 hover:text-foreground">
              {entry.source_meeting_title ?? "a meeting"}
            </Link>
          </>
        )}
      </>
    );
  }
  if (entry.source === "learned") {
    return (
      <>
        Learned when {entry.created_by ?? "someone"} fixed it
        {entry.source_meeting_id && (
          <>
            {" in "}
            <Link href={`/meetings/${entry.source_meeting_id}`} className="underline underline-offset-2 hover:text-foreground">
              {entry.source_meeting_title ?? "a meeting"}
            </Link>
          </>
        )}
        {entry.times_confirmed > 1 && ` · confirmed ${entry.times_confirmed} times`}
      </>
    );
  }
  return <>Added by {entry.created_by ?? "a former teammate"}</>;
}

/** Mishearings Charcha noticed on its own: a word that sounds like an
 * invitee's name but isn't spelled like it, backed by Meet's captions when
 * the notetaker recorded them. */
function SuggestionsCard({
  suggestions,
  onDecided,
  onError,
}: {
  suggestions: VocabularySuggestion[];
  onDecided: (id: string, accepted: boolean) => void;
  onError: (message: string) => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);

  async function decide(suggestion: VocabularySuggestion, accept: boolean) {
    setBusyId(suggestion.id);
    try {
      if (accept) await api.acceptVocabularySuggestion(suggestion.id, true);
      else await api.dismissVocabularySuggestion(suggestion.id);
      onDecided(suggestion.id, accept);
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : "That wasn't saved");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Card className="border-primary/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" /> Suggested corrections ({suggestions.length})
        </CardTitle>
        <CardDescription>
          Words in your meetings that sound like someone who was invited but aren&apos;t spelled like them. Accept one to fix it everywhere, including past meetings. Ones nobody decides on are applied once they&apos;ve been heard in enough meetings.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col divide-y">
        {suggestions.map((suggestion) => (
          <div key={suggestion.id} className="flex flex-wrap items-center gap-3 py-3">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <p className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground line-through decoration-muted-foreground/60">{suggestion.heard_as}</span>
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="font-medium">{suggestion.term}</span>
                {suggestion.reason === "captions" && (
                  <Badge variant="outline" title="Meet's captions had this name at the same moment">
                    <Captions className="h-3 w-3" /> Captions agree
                  </Badge>
                )}
              </p>
              <p className="text-xs text-muted-foreground">
                Heard {suggestion.occurrences} time{suggestion.occurrences === 1 ? "" : "s"} in {suggestion.meetings} meeting{suggestion.meetings === 1 ? "" : "s"}
                {suggestion.meeting_id && (
                  <>
                    {", most recently "}
                    <Link href={`/meetings/${suggestion.meeting_id}`} className="underline underline-offset-2 hover:text-foreground">
                      {suggestion.meeting_title ?? "a meeting"}
                    </Link>
                  </>
                )}
                {suggestion.auto_apply_at !== null && suggestion.meetings < suggestion.auto_apply_at &&
                  ` · applied automatically after ${suggestion.auto_apply_at} meetings`}
              </p>
            </div>
            <Button size="sm" disabled={busyId === suggestion.id} onClick={() => void decide(suggestion, true)}>
              {busyId === suggestion.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Accept
            </Button>
            <Button size="sm" variant="ghost" disabled={busyId === suggestion.id} onClick={() => void decide(suggestion, false)}>
              <X className="h-3.5 w-3.5" /> Not a mistake
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const KIND_LABEL: Record<VocabularyPerson["kind"], string> = {
  account: "Charcha account",
  added: "Guest",
  roster: "Server roster",
  guest: "Regular guest",
};
const COLLAPSED_PEOPLE = 12;

/** Whose names are listened for, and how transcription has misheard them.
 * Accounts are automatic; guests without an account can be added; people
 * who keep turning up in your meetings are offered. */
function TeammatesCard({
  people,
  total,
  searching,
  onChanged,
  onToggle,
}: {
  people: VocabularyPerson[];
  total: number;
  searching: boolean;
  onChanged: () => void;
  onToggle: (ruleId: string, enabled: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [variants, setVariants] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function addPerson(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await api.addVocabularyPerson({ name: name.trim(), note: note.trim() || undefined });
      setName("");
      setNote("");
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That person couldn't be added");
    } finally {
      setAdding(false);
    }
  }

  async function keep(person: VocabularyPerson) {
    setBusyId(person.id);
    try {
      await api.addVocabularyPerson({ name: person.name });
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That person couldn't be added");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(person: VocabularyPerson) {
    setBusyId(person.id);
    try {
      await api.deleteVocabularyPerson(person.id);
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That person couldn't be removed");
    } finally {
      setBusyId(null);
    }
  }

  async function addHeardAs(event: FormEvent, person: VocabularyPerson) {
    event.preventDefault();
    const heardAs = variants.split(",").map((value) => value.trim()).filter(Boolean);
    if (!heardAs.length) return;
    setBusyId(person.id);
    setError(null);
    try {
      await api.addVocabulary({ term: person.name, heard_as: heardAs, fix_past: true });
      setEditingId(null);
      setVariants("");
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That couldn't be added");
    } finally {
      setBusyId(null);
    }
  }

  const shown = showAll || searching ? people : people.slice(0, COLLAPSED_PEOPLE);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Users className="h-4 w-4" /> Teammates ({total})
        </CardTitle>
        <CardDescription>
          Everyone with a Charcha account is listened for automatically, with the people invited to a meeting first. Add clients, vendors and other regular guests, and teach Charcha how a name tends to be misheard, for example “Arshit, Orchid” for Archit. Notes use these spellings too.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={addPerson} className="flex flex-wrap items-end gap-2">
          <div className="grid min-w-40 flex-1 gap-1.5">
            <Label htmlFor="person-name">Guest&apos;s name</Label>
            <Input id="person-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Priya Raman" maxLength={80} />
          </div>
          <div className="grid min-w-40 flex-1 gap-1.5">
            <Label htmlFor="person-note">Who they are (optional)</Label>
            <Input id="person-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Client at Acme" maxLength={200} />
          </div>
          <Button type="submit" size="sm" disabled={adding || !name.trim()}>
            {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />} Add guest
          </Button>
        </form>
        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-col divide-y">
          {shown.length === 0 && <p className="py-2 text-sm text-muted-foreground">{searching ? "Nobody matches." : "Nobody yet."}</p>}
          {shown.map((person) => (
            <div key={person.id} className="flex flex-col gap-2 py-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium uppercase">
                  {person.name.split(" ").map((part) => part[0]).slice(0, 2).join("")}
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <p className="text-sm font-medium">{person.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {KIND_LABEL[person.kind]}
                    {person.meetings ? ` · in ${person.meetings} of your meetings` : ""}
                    {person.note ? ` · ${person.note}` : ""}
                  </p>
                </div>
                {person.kind === "guest" && (
                  <Button size="sm" variant="outline" disabled={busyId === person.id} onClick={() => void keep(person)}>
                    <Plus className="h-3.5 w-3.5" /> Always listen
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => { setEditingId(editingId === person.id ? null : person.id); setVariants(""); }}>
                  <Plus className="h-3.5 w-3.5" /> Heard as
                </Button>
                {person.can_delete && (
                  <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" disabled={busyId === person.id} onClick={() => void remove(person)} aria-label={`Remove ${person.name}`}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
              {(person.heard_as.length > 0 || editingId === person.id) && (
                <div className="flex flex-wrap items-center gap-2 pl-11">
                  {person.heard_as.map((rule) => (
                    <span key={rule.id} className={`flex items-center gap-1 rounded-md border py-0.5 pl-2 pr-1 text-xs ${rule.enabled ? "" : "opacity-60 line-through"}`}>
                      heard as “{rule.heard_as}”
                      <button
                        type="button"
                        className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                        onClick={() => onToggle(rule.id, !rule.enabled)}
                        aria-label={rule.enabled ? `Switch off ${rule.heard_as}` : `Switch on ${rule.heard_as}`}
                        title={rule.enabled ? "Switch off" : "Switch on"}
                      >
                        {rule.enabled ? <X className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      </button>
                    </span>
                  ))}
                  {editingId === person.id && (
                    <form onSubmit={(event) => void addHeardAs(event, person)} className="flex items-center gap-2">
                      <Input autoFocus value={variants} onChange={(event) => setVariants(event.target.value)} placeholder="Misspellings, comma-separated" className="h-7 w-56 text-xs" maxLength={400} aria-label={`How ${person.name} is misheard`} />
                      <Button type="submit" size="sm" disabled={busyId === person.id || !variants.trim()}>Save</Button>
                    </form>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
        {!searching && people.length > COLLAPSED_PEOPLE && (
          <Button variant="ghost" size="sm" className="self-start" onClick={() => setShowAll(!showAll)}>
            {showAll ? "Show fewer" : `Show all ${people.length}`}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
