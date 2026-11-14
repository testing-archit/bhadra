"use client";

import { useState } from "react";
import { EyeOff, Send, UserX } from "lucide-react";
import { api, ApiError, type MeetingTask, type OwnerAccess } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** A task whose owner wasn't in the meeting: they don't see it until the
 * recorder or organizer sends it — the task only, never the meeting. */
export function TaskOwnerAccess({
  task,
  canManage,
  onChanged,
}: {
  task: MeetingTask;
  canManage: boolean;
  onChanged: (access: OwnerAccess) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const access = task.owner_access;
  if (!access || access === "meeting") return null;
  const owner = task.owner || "The owner";

  async function decide(action: "send" | "keep_private") {
    setBusy(true);
    setError(null);
    try {
      const result = await api.setTaskOwnerAccess(task.id, action);
      onChanged(result.owner_access);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not change this");
    } finally {
      setBusy(false);
    }
  }

  const send = canManage && access !== "shared" && (
    <Button variant="outline" size="xs" onClick={() => void decide("send")} disabled={busy}>
      <Send />
      {busy ? "Sending…" : `Send to ${owner.split(" ")[0]}`}
    </Button>
  );

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
      {access === "held" && (
        <>
          <span className="flex items-center gap-1 text-warning">
            <UserX className="size-3.5" />
            {owner} wasn&apos;t in this meeting and can&apos;t see this task yet.
          </span>
          {send}
          {canManage && (
            <Button variant="ghost" size="xs" onClick={() => void decide("keep_private")} disabled={busy}>
              <EyeOff />
              Keep private
            </Button>
          )}
        </>
      )}
      {access === "shared" && (
        <span className="text-muted-foreground">Sent to {owner} — the task only, not the meeting.</span>
      )}
      {access === "private" && (
        <>
          <span className="flex items-center gap-1 text-muted-foreground">
            <EyeOff className="size-3.5" />
            Kept private from {owner}.
          </span>
          {send}
        </>
      )}
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}
