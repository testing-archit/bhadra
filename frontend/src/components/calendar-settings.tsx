"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CalendarDays, CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import { api, ApiError, type CalendarState, type CalendarConnectionInfo } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const MODES: { value: CalendarConnectionInfo["auto_join"]; label: string; detail: string }[] = [
  { value: "all", label: "Every meeting", detail: "Any event with a Google Meet link that you haven't declined, including calls with clients." },
  { value: "organized", label: "Meetings I organize", detail: "Only events you created. Others you can switch on one by one." },
  { value: "manual", label: "Only ones I pick", detail: "Nothing joins until you switch a meeting on from Home." },
];

/** Settings card for linking a Google Calendar so the notetaker follows the
 * person to their meetings. */
export function CalendarSettings() {
  const [state, setState] = useState<CalendarState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    api.getCalendar().then(setState).catch(() => setState({ configured: false, connection: null }));
    // Google sends people back here after the consent screen.
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("calendar");
    if (outcome) {
      if (outcome === "connected") setMessage({ tone: "ok", text: "Calendar linked. The notetaker will join your upcoming meetings." });
      else if (outcome === "error") setMessage({ tone: "error", text: params.get("message") || "The calendar couldn't be linked. Try again." });
      const url = new URL(window.location.href);
      url.searchParams.delete("calendar");
      url.searchParams.delete("message");
      window.history.replaceState(null, "", url);
    }
  }, []);

  async function run<T>(key: string, action: () => Promise<T>, after?: (value: T) => void) {
    setBusy(key);
    setMessage(null);
    try {
      const value = await action();
      after?.(value);
    } catch (cause) {
      setMessage({ tone: "error", text: cause instanceof ApiError ? cause.message : "That didn't work. Try again." });
    } finally {
      setBusy(null);
    }
  }

  const connection = state?.connection;

  return (
    <Card id="calendar">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarDays className="h-4 w-4 text-primary" /> Google Calendar
        </CardTitle>
        <CardDescription>
          Link your calendar and the notetaker follows you to your Google Meet calls. A meeting several colleagues share is
          still recorded once, and everyone invited gets the notes.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!state && <p className="text-sm text-muted-foreground">Loading…</p>}

        {state && !state.configured && (
          <p className="rounded-lg border border-dashed px-3 py-3 text-sm text-muted-foreground">
            Calendar linking isn&apos;t switched on for this workspace yet. An admin needs to add the Google OAuth client to the server.
          </p>
        )}

        {state?.configured && !connection && (
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm text-muted-foreground">
              Wilco only reads your events (title, time, Meet link and who&apos;s invited). It never changes your calendar.
            </p>
            <Button onClick={() => void run("connect", api.connectCalendar, ({ url }) => (window.location.href = url))} disabled={busy === "connect"}>
              {busy === "connect" ? <Loader2 className="animate-spin" /> : <CalendarDays />} Link Google Calendar
            </Button>
          </div>
        )}

        {connection && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 px-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{connection.google_email}</p>
                <p className="text-xs text-muted-foreground">
                  {connection.status === "error"
                    ? "Not syncing"
                    : connection.last_synced_at
                      ? `Synced ${new Date(connection.last_synced_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
                      : "Syncing…"}
                  {connection.status !== "error" &&
                    (connection.live_updates ? (
                      <span title="Google tells Wilco the moment your calendar changes, so meetings added at the last minute are still joined."> · Live updates on</span>
                    ) : (
                      <span title={connection.live_updates_error ?? undefined}> · Checked every minute</span>
                    ))}
                </p>
              </div>
              <div className="flex gap-1.5">
                <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void run("sync", api.syncCalendar, (info) => setState((s) => (s ? { ...s, connection: info } : s)))}>
                  {busy === "sync" ? <Loader2 className="animate-spin" /> : <RefreshCw />} Sync now
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground hover:text-destructive"
                  disabled={!!busy}
                  onClick={() => void run("disconnect", api.disconnectCalendar, () => setState((s) => (s ? { ...s, connection: null } : s)))}
                >
                  Unlink
                </Button>
              </div>
            </div>

            {connection.status === "error" && (
              <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                <div className="flex-1">
                  <p>{connection.last_error || "Google stopped sharing your calendar with Wilco."}</p>
                  <Button size="sm" className="mt-2" onClick={() => void run("connect", api.connectCalendar, ({ url }) => (window.location.href = url))}>
                    Reconnect
                  </Button>
                </div>
              </div>
            )}

            <div>
              <p className="mb-2 text-sm font-medium">Send the notetaker to</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Which meetings to record">
                {MODES.map((mode) => (
                  <button
                    key={mode.value}
                    type="button"
                    role="radio"
                    aria-checked={connection.auto_join === mode.value}
                    disabled={!!busy}
                    onClick={() =>
                      void run("mode", () => api.updateCalendar(mode.value), (info) => setState((s) => (s ? { ...s, connection: info } : s)))
                    }
                    className={cn(
                      "rounded-xl border p-3 text-left transition-colors hover:bg-muted",
                      connection.auto_join === mode.value && "border-primary bg-primary/5 hover:bg-primary/5",
                    )}
                  >
                    <span className={cn("block text-sm font-medium", connection.auto_join === mode.value && "text-primary")}>{mode.label}</span>
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">{mode.detail}</span>
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Switch individual meetings on or off from Home under &ldquo;Coming up&rdquo;.</p>
            </div>
          </>
        )}

        {message && (
          <p className={cn("flex items-center gap-1.5 text-sm", message.tone === "ok" ? "text-success" : "text-destructive")} role="status">
            {message.tone === "ok" && <CheckCircle2 className="size-4" />}
            {message.text}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
