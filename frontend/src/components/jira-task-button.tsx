"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, Send, Unlink } from "lucide-react";
import { api, ApiError, jiraIssueUrl, type JiraStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";

let cached: Promise<JiraStatus> | null = null;

/** Whether Jira is connected (and its site, for issue links). Fetched once
 * per page load and shared; null while loading or when the call fails. */
export function useJiraStatus(): JiraStatus | null {
  const [status, setStatus] = useState<JiraStatus | null>(null);
  useEffect(() => {
    cached ??= api.jiraStatus().catch(() => {
      cached = null;
      return { connected: false, site_url: null };
    });
    let live = true;
    void cached.then((value) => live && setStatus(value));
    return () => {
      live = false;
    };
  }, []);
  return status;
}

/** The issue link once a task is in Jira, else "Send to Jira" — nothing at
 * all when Jira isn't connected. */
export function JiraTaskButton({
  taskId,
  issueKey,
  issueStatus,
  issueError,
  jira,
  onSent,
  compact=false,
}: {
  taskId: string;
  issueKey?: string | null;
  issueStatus?: string | null;
  issueError?: string | null;
  jira: JiraStatus | null;
  onSent: (key: string, status: string | null) => void;
  compact?:boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const url = jiraIssueUrl(jira, issueKey);

  const warning = issueError ? (
    <span title={issueError} className="inline-flex items-center text-destructive" aria-label={`Jira sync problem: ${issueError}`}>
      <AlertTriangle className="h-3 w-3" />
    </span>
  ) : null;

  if (issueKey) {
    const label = issueStatus ? `${issueKey} · ${issueStatus}` : issueKey;
    const link = url ? (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground hover:text-foreground"
        title="Open in Jira"
      >
        {label}
        <ExternalLink className="h-3 w-3" />
      </a>
    ) : (
      <span className="rounded-md border px-1.5 py-0.5 text-[11px] text-muted-foreground">{label}</span>
    );
    return (
      <span className="inline-flex items-center gap-1">
        {link}
        {warning}
      </span>
    );
  }
  if (!jira?.connected) return null;

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.sendTaskToJira(taskId);
      onSent(result.jira_issue_key, result.jira_status);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Couldn't create the Jira issue");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <Button variant="ghost" size="xs" disabled={busy} onClick={() => void send()} title="Create a Jira issue for this task">
        <Send />
        {busy ? "Sending…" : compact?"Jira":"Send to Jira"}
      </Button>
      {error && <span className="text-[11px] text-destructive">{error}</span>}
    </span>
  );
}

/** Settings → Jira: where people look for integrations. The setup itself
 * lives in Admin → Integrations; this says whether it's on and links there. */
export function JiraSettingsCard({ isAdmin }: { isAdmin: boolean }) {
  const jira = useJiraStatus();
  const site = jira?.site_url?.replace("https://", "");
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="flex items-center gap-2 text-base font-medium">
          <Send className="h-4 w-4 text-primary" /> Jira
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {jira === null
            ? "Checking…"
            : jira.connected
              ? `Connected to ${site}. Use "Send to Jira" on any task; status stays in step both ways.`
              : isAdmin
                ? "Not connected yet. Connect your Jira Cloud site so tasks can be sent to Jira."
                : "Not connected yet. An admin can connect Jira in Admin → Integrations."}
        </p>
      </div>
      {isAdmin && (
        <a
          href="/admin?tab=integrations"
          className="inline-flex h-8 shrink-0 items-center gap-1.5 self-start rounded-lg border px-2.5 text-sm font-medium hover:bg-muted sm:self-auto"
        >
          {jira?.connected ? "Manage Jira" : "Connect Jira"}
        </a>
      )}
    </div>
  );
}


/** Jira on the task dialog: where the task lives in Jira, what syncs, and
 * Send / Unlink. Renders nothing when Jira isn't connected and the task was
 * never sent. */
export function JiraTaskPanel({
  taskId,
  issueKey,
  issueStatus,
  issueError,
  onChange,
}: {
  taskId: string;
  issueKey?: string | null;
  issueStatus?: string | null;
  issueError?: string | null;
  onChange?: (fields: { jira_issue_key: string | null; jira_status: string | null; jira_error: string | null }) => void;
}) {
  const jira = useJiraStatus();
  const [state, setState] = useState({ key: issueKey ?? null, status: issueStatus ?? null, error: issueError ?? null });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const url = jiraIssueUrl(jira, state.key);

  if (!state.key && !jira?.connected && !state.error) return null;

  function update(next: typeof state) {
    setState(next);
    onChange?.({ jira_issue_key: next.key, jira_status: next.status, jira_error: next.error });
  }

  async function send() {
    setBusy(true);
    setFailure(null);
    try {
      const result = await api.sendTaskToJira(taskId);
      update({ key: result.jira_issue_key, status: result.jira_status, error: null });
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : "Couldn't create the Jira issue");
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    if (!window.confirm(`Stop syncing with ${state.key}? The Jira issue itself stays as it is.`)) return;
    setBusy(true);
    setFailure(null);
    try {
      await api.unlinkTaskFromJira(taskId);
      update({ key: null, status: null, error: null });
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : "Couldn't unlink");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">Jira</span>
        {state.key ? (
          <span className="flex items-center gap-1.5">
            {url ? (
              <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium hover:underline">
                {state.key}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : (
              <span className="font-medium">{state.key}</span>
            )}
            {state.status && <span className="text-muted-foreground">· {state.status}</span>}
            <Button variant="ghost" size="xs" disabled={busy} onClick={() => void unlink()} title="Stop syncing with this issue">
              <Unlink /> Unlink
            </Button>
          </span>
        ) : jira?.connected ? (
          <Button variant="outline" size="xs" disabled={busy} onClick={() => void send()}>
            <Send />
            {busy ? "Sending…" : "Send to Jira"}
          </Button>
        ) : null}
      </div>
      {state.key && (
        <p className="text-xs text-muted-foreground">
          Text, owner, due date, priority, status and comments stay in sync both ways.
        </p>
      )}
      {(state.error || failure) && (
        <p className="flex items-start gap-1.5 text-xs text-destructive">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {failure || state.error}
        </p>
      )}
    </div>
  );
}
