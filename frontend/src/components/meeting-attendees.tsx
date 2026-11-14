"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Lock, Pencil, Search, Share2, UserPlus, Users, X } from "lucide-react";
import { api, ApiError, AttendeeInput, DirectoryUser, MeetingAttendee } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type ExternalMember = { name: string; email: string };

const SOURCE_LABELS: Record<MeetingAttendee["source"], string> = {
  recorder: "Recorded it",
  calendar: "Invited",
  requested: "Asked for notes",
  shared: "Shared with",
  manual: "Added",
  meet: "In the call",
  jira: "Jira team (a task is in Jira)",
};

/**
 * Who was in the meeting, and who can read its notes.
 *
 * Access follows the invite: the recorder, calendar invitees and colleagues
 * who asked for the notetaker can read it. People the notetaker heard in the
 * call who weren't invited wait in "pending" until the organizer, the person
 * who recorded it, or a Charcha admin shares it with them.
 */
export function MeetingAttendees({
  meetingId,
  attendees,
  canManage,
  onChange,
}: {
  meetingId: string;
  attendees: MeetingAttendee[];
  canManage: boolean;
  onChange: (next: MeetingAttendee[]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [externals, setExternals] = useState<ExternalMember[]>([]);
  const [externalName, setExternalName] = useState("");
  const [externalEmail, setExternalEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shareQuery, setShareQuery] = useState("");
  const [sharing, setSharing] = useState(false);

  const granted = attendees.filter((item) => item.kind === "internal" && item.access === "granted");
  const pending = attendees.filter((item) => item.kind === "internal" && item.access === "pending");
  const external = attendees.filter((item) => item.kind === "external");
  const pendingIds = useMemo(() => new Set(pending.map((item) => item.user_id)), [pending]);

  useEffect(() => {
    if (!canManage) return;
    if (!editing && !sharing) return;
    api.getDirectory().then(setDirectory).catch(() => setDirectory([]));
  }, [canManage, editing, sharing]);

  // Fill the editor when it opens — not on every reload of the meeting,
  // which would wipe changes someone is in the middle of making.
  const attendeesRef = useRef(attendees);
  useEffect(() => {
    attendeesRef.current = attendees;
  }, [attendees]);
  useEffect(() => {
    if (!editing) return;
    const current = attendeesRef.current;
    setMemberIds(current.filter((item) => item.user_id).map((item) => item.user_id as string));
    setExternals(current.filter((item) => !item.user_id).map((item) => ({ name: item.name, email: item.email ?? "" })));
    setError(null);
  }, [editing]);

  async function setAccess(person: MeetingAttendee, access: "granted" | "pending") {
    setBusyId(person.id);
    setError(null);
    try {
      onChange(await api.setAttendeeAccess(meetingId, person.id, access));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Access couldn't be changed.");
    } finally {
      setBusyId(null);
    }
  }

  async function shareWith(person: DirectoryUser) {
    setBusyId(person.id);
    setError(null);
    try {
      onChange(await api.shareMeeting(meetingId, person.id));
      setShareQuery("");
      setSharing(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The meeting couldn't be shared.");
    } finally {
      setBusyId(null);
    }
  }

  function addExternal() {
    const label = externalName.trim() || externalEmail.trim();
    if (!label) return;
    if (externals.some((guest) => guest.name.toLowerCase() === label.toLowerCase())) return;
    setExternals((current) => [...current, { name: label, email: externalEmail.trim() }]);
    setExternalName("");
    setExternalEmail("");
  }

  async function save() {
    setSaving(true);
    setError(null);
    const payload: AttendeeInput[] = [
      ...memberIds.map((id) => {
        const person = directory.find((item) => item.id === id) ?? attendees.find((item) => item.user_id === id);
        // Ticking someone in this list doesn't share the notes with a person
        // who is still pending — that's an explicit "Share" decision.
        return { user_id: id, name: person?.name ?? "", email: person?.email ?? null, access: pendingIds.has(id) ? ("pending" as const) : ("granted" as const) };
      }),
      ...externals.map((guest) => ({ user_id: null, name: guest.name, email: guest.email || null })),
    ];
    try {
      onChange(await api.setMeetingAttendees(meetingId, payload));
      setEditing(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save the attendee list.");
    } finally {
      setSaving(false);
    }
  }

  const shareCandidates = useMemo(() => {
    const taken = new Set(granted.map((item) => item.user_id));
    const needle = shareQuery.trim().toLowerCase();
    return directory
      .filter((person) => !taken.has(person.id))
      .filter((person) => !needle || person.name.toLowerCase().includes(needle) || person.email.toLowerCase().includes(needle))
      .slice(0, 8);
  }, [directory, granted, shareQuery]);

  return (
    <Card id="people">
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Users className="h-4 w-4 text-primary" />
          People and access
        </CardTitle>
        {canManage && !editing && (
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setSharing((value) => !value)} aria-expanded={sharing}>
              <Share2 className="h-3.5 w-3.5" /> Share
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              <Pencil className="h-3.5 w-3.5" /> Edit list
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {!editing ? (
          <>
            {sharing && canManage && (
              <div className="rounded-lg border bg-muted/30 p-3">
                <div className="relative">
                  <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    autoFocus
                    value={shareQuery}
                    onChange={(event) => setShareQuery(event.target.value)}
                    placeholder="Share with a colleague"
                    className="h-9 pl-8"
                    aria-label="Find a colleague to share with"
                  />
                </div>
                <div className="mt-2 flex flex-col">
                  {shareCandidates.map((person) => (
                    <button
                      key={person.id}
                      type="button"
                      disabled={busyId === person.id}
                      onClick={() => void shareWith(person)}
                      className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                    >
                      <span className="min-w-0">
                        <span className="block truncate">{person.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{person.email}</span>
                      </span>
                      {busyId === person.id ? <Loader2 className="size-4 animate-spin" /> : <span className="text-xs text-primary">Share</span>}
                    </button>
                  ))}
                  {directory.length > 0 && shareCandidates.length === 0 && (
                    <p className="px-2 py-1.5 text-sm text-muted-foreground">Everyone matching already has access.</p>
                  )}
                </div>
              </div>
            )}

            <section>
              <p className="mb-2 text-xs font-medium text-muted-foreground">Can read these notes</p>
              <ul className="flex flex-col gap-1">
                {granted.map((person) => (
                  <li key={person.id} className="group flex items-center gap-2.5 rounded-md py-1">
                    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/12 text-[11px] font-semibold text-primary">
                      {person.name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{person.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{SOURCE_LABELS[person.source] ?? "Has access"}</span>
                    </span>
                    {canManage && person.source !== "recorder" && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-destructive"
                        disabled={busyId === person.id}
                        onClick={() => void setAccess(person, "pending")}
                        aria-label={`Remove ${person.name}'s access`}
                        title="Remove access"
                      >
                        <X />
                      </Button>
                    )}
                  </li>
                ))}
                {granted.length === 0 && <p className="text-sm text-muted-foreground">Only the person who recorded it.</p>}
              </ul>
            </section>

            {pending.length > 0 && (
              <section className="rounded-lg border border-warning/40 bg-warning/5 p-3">
                <p className="text-sm font-medium">In the call, not on the invite</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {canManage
                    ? "They can't read the notes until you share them."
                    : "The organizer or a Charcha admin decides whether to share the notes with them."}
                </p>
                <ul className="mt-2 flex flex-col gap-1">
                  {pending.map((person) => (
                    <li key={person.id} className="flex items-center gap-2.5 py-1">
                      <Lock className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-sm">{person.name}</span>
                      {canManage && (
                        <Button size="sm" variant="outline" disabled={busyId === person.id} onClick={() => void setAccess(person, "granted")}>
                          {busyId === person.id ? <Loader2 className="animate-spin" /> : <Share2 />} Share notes
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {external.length > 0 && (
              <section>
                <p className="mb-2 text-xs font-medium text-muted-foreground">Guests outside Charcha</p>
                <div className="flex flex-wrap gap-1.5">
                  {external.map((person) => (
                    <span key={person.id} className={cn("rounded-full border border-dashed px-2.5 py-0.5 text-xs text-muted-foreground")} title={person.email ?? undefined}>
                      {person.name}
                    </span>
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">Guests are on the record but can&apos;t open it. Use a share link to send them the notes.</p>
              </section>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}
          </>
        ) : (
          <>
            <div className="grid gap-2">
              <Label className="text-sm">Colleagues in this meeting</Label>
              <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
                {directory.map((person) => (
                  <label key={person.id} className="flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm">
                    <Checkbox
                      checked={memberIds.includes(person.id)}
                      onCheckedChange={(checked) =>
                        setMemberIds((current) => (checked === true ? [...current, person.id] : current.filter((item) => item !== person.id)))
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate">{person.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{pendingIds.has(person.id) ? "Pending — not shared yet" : person.email}</span>
                    </span>
                  </label>
                ))}
                {directory.length === 0 && <p className="text-sm text-muted-foreground">Loading your team…</p>}
              </div>
              <p className="text-xs text-muted-foreground">Colleagues you add here can read the notes. Pending people stay pending until you share with them.</p>
            </div>

            <div className="grid gap-2 rounded-md border border-dashed p-3">
              <Label className="text-sm">Guests outside Charcha</Label>
              <div className="flex flex-wrap gap-2">
                <Input
                  value={externalName}
                  onChange={(event) => setExternalName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addExternal();
                    }
                  }}
                  placeholder="Name"
                  className="h-9 min-w-32 flex-1"
                />
                <Input
                  value={externalEmail}
                  onChange={(event) => setExternalEmail(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addExternal();
                    }
                  }}
                  placeholder="Email (optional)"
                  type="email"
                  className="h-9 min-w-32 flex-1"
                />
                <Button type="button" variant="outline" size="sm" className="h-9 gap-1.5" onClick={addExternal} disabled={!externalName.trim() && !externalEmail.trim()}>
                  <UserPlus className="h-3.5 w-3.5" /> Add
                </Button>
              </div>
              {externals.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {externals.map((guest) => (
                    <span key={guest.name} className="flex items-center gap-1.5 rounded-full border bg-muted px-3 py-1 text-xs">
                      {guest.name}
                      <button
                        type="button"
                        aria-label={`Remove ${guest.name}`}
                        onClick={() => setExternals((current) => current.filter((item) => item.name !== guest.name))}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex gap-2">
              <Button size="sm" onClick={save} disabled={saving}>
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                Save
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
