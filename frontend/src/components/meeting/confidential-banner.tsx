"use client";

import { useState } from "react";
import { Lock, LockOpen } from "lucide-react";
import { api, ApiError, type MeetingDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** "Mark confidential" for anyone in the meeting (the server checks). */
export function MarkConfidentialButton({ meeting, onChanged }: { meeting: MeetingDetail; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (meeting.confidential) return null;

  async function mark() {
    setBusy(true);
    setError(null);
    try {
      await api.setMeetingConfidential(meeting.id, true);
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not mark it confidential");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => void mark()}
      disabled={busy}
      title={error ?? "Only the people in this meeting will be able to open it, admins included"}
      className={error ? "text-destructive" : undefined}
    >
      <Lock className="h-4 w-4" />
      {busy ? "Marking…" : error ? "Couldn't mark it" : "Mark confidential"}
    </Button>
  );
}

/** Shown under the title of a confidential meeting: who can open it, why
 * it was marked, and — for the recorder or organizer — the way back. */
export function ConfidentialNotice({ meeting, onChanged }: { meeting: MeetingDetail; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!meeting.confidential) return null;

  async function unmark() {
    setBusy(true);
    setError(null);
    try {
      await api.setMeetingConfidential(meeting.id, false);
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not unmark it");
    } finally {
      setBusy(false);
    }
  }

  const byAi = meeting.confidential_source === "ai";
  return (
    <div className="mt-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Lock className="size-4 shrink-0 text-warning" />
        <span className="min-w-0 flex-1">
          <strong className="font-medium">Confidential.</strong>{" "}
          {byAi
            ? `Wilco marked it because it discusses ${meeting.confidential_reason || "a sensitive matter"}. `
            : ""}
          Only the people in this meeting can open it, Wilco admins included. It isn&apos;t sent to Jira, and its tasks
          reach no one else unless you send them.
        </span>
        {meeting.can_unmark_confidential && (
          <Button variant="ghost" size="xs" onClick={() => void unmark()} disabled={busy}>
            <LockOpen />
            {busy ? "Unmarking…" : "Not confidential"}
          </Button>
        )}
      </div>
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}
