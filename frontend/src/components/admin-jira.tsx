"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowDownLeft, CircleCheck, ExternalLink, KeyRound, Link2, LogIn, RefreshCw, Unplug, Users } from "lucide-react";
import { api, ApiError, jiraIssueUrl, type JiraActivity, type JiraPeople, type JiraProjects, type JiraSettings } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

const TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens";

function message(cause: unknown, fallback: string) {
  return cause instanceof ApiError ? cause.message : fallback;
}

/** Admin → Integrations: the company's Jira Cloud connection. "Connect with
 * Jira" (Atlassian sign-in) when the server has an Atlassian app, with an
 * API token as the fallback. */
export function AdminJira() {
  const [settings, setSettings] = useState<JiraSettings | null>(null);
  const [projects, setProjects] = useState<JiraProjects | null>(null);
  const [tokenForm, setTokenForm] = useState({ site_url: "", email: "", api_token: "", default_project_key: "" });
  const [defaultProject, setDefaultProject] = useState("");
  const [projectMap, setProjectMap] = useState<Record<string, string>>({});
  const [autoSend, setAutoSend] = useState<"off" | "mapped" | "all">("off");
  const [showToken, setShowToken] = useState(false);
  const [busy, setBusy] = useState<"oauth" | "token" | "projects" | "sync" | "disconnect" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback((value: JiraSettings) => {
    setSettings(value);
    setTokenForm({ site_url: value.site_url ?? "", email: value.email ?? "", api_token: "", default_project_key: value.default_project_key ?? "" });
    setDefaultProject(value.default_project_key ?? "");
    setProjectMap(value.project_map ?? {});
    setAutoSend(value.auto_send ?? "off");
    if (value.connected) {
      api.adminJiraProjects().then(setProjects).catch((cause) => setError(message(cause, "Couldn't load Jira projects")));
    } else {
      setProjects(null);
    }
  }, []);

  useEffect(() => {
    // Back from Atlassian's consent screen: /admin?tab=integrations&jira=…
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("jira");
    if (outcome === "connected") setNotice("Jira is connected. Pick the default project below to finish.");
    if (outcome === "cancelled") setNotice("Jira sign-in was cancelled.");
    if (outcome === "error") setError(params.get("message") || "Couldn't connect Jira");
    if (outcome) {
      params.delete("jira");
      params.delete("message");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    }
    api.adminJira().then(apply).catch((cause) => setError(message(cause, "Couldn't load the Jira settings")));
  }, [apply]);

  async function connectWithJira() {
    setBusy("oauth");
    setError(null);
    try {
      const { url } = await api.startJiraOAuth();
      window.location.href = url;
    } catch (cause) {
      setError(message(cause, "Couldn't start the Jira sign-in"));
      setBusy(null);
    }
  }

  async function saveToken() {
    setBusy("token");
    setError(null);
    setNotice(null);
    try {
      apply(
        await api.saveAdminJira({
          site_url: tokenForm.site_url,
          email: tokenForm.email,
          api_token: tokenForm.api_token || undefined,
          default_project_key: tokenForm.default_project_key,
          project_map: projectMap,
        })
      );
      setShowToken(false);
      setNotice("Saved — Jira is connected.");
    } catch (cause) {
      setError(message(cause, "Couldn't connect to Jira"));
    } finally {
      setBusy(null);
    }
  }

  async function saveProjects() {
    setBusy("projects");
    setError(null);
    setNotice(null);
    try {
      apply(await api.saveAdminJiraProjects({ default_project_key: defaultProject, project_map: projectMap, auto_send: autoSend }));
      setNotice("Saved. Tasks can now be sent to Jira.");
    } catch (cause) {
      setError(message(cause, "Couldn't save the projects"));
    } finally {
      setBusy(null);
    }
  }

  async function sync() {
    setBusy("sync");
    setError(null);
    try {
      const result = await api.syncAdminJira();
      setSettings(result);
      setNotice(result.changed ? `Updated ${result.changed} task${result.changed === 1 ? "" : "s"} from Jira.` : "Everything is already in step with Jira.");
    } catch (cause) {
      setError(message(cause, "Sync failed"));
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Jira? Existing issue links on tasks are kept.")) return;
    setBusy("disconnect");
    setError(null);
    try {
      apply(await api.disconnectAdminJira());
      setNotice("Jira disconnected.");
    } catch (cause) {
      setError(message(cause, "Couldn't disconnect"));
    } finally {
      setBusy(null);
    }
  }

  if (!settings && !error) return <Skeleton className="h-96 w-full rounded-xl" />;
  const connected = !!settings?.connected;
  const oauth = !!settings?.oauth_available;
  // Rows left on "default" follow the default if it changes later, so the
  // option names whichever project that currently is.
  const defaultName = projects?.jira.find((p) => p.key === defaultProject);
  const defaultLabel = defaultName ? `Default · ${defaultName.name} (${defaultName.key})` : "Default project";
  const tokenFormVisible = (!connected && (!oauth || showToken)) || (connected && showToken);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Jira</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Send meeting tasks to Jira. Once linked, the task text, owner (assignee), due date, priority, status and comments stay in
          sync both ways — an edit on either side shows up on the other within two minutes. Works on Jira Free.
        </p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {notice && !error && <p className="text-sm text-muted-foreground">{notice}</p>}

      {!connected && oauth && (
        <div className="flex flex-col items-start gap-3 rounded-xl border bg-card p-5">
          <p className="text-sm">Sign in with the Atlassian account that should create the issues, and approve Charcha&apos;s access.</p>
          <Button disabled={busy !== null} onClick={() => void connectWithJira()}>
            {busy === "oauth" ? <RefreshCw className="animate-spin" /> : <LogIn />}
            Connect with Jira
          </Button>
          {!showToken && (
            <button type="button" className="text-xs text-muted-foreground underline-offset-4 hover:underline" onClick={() => setShowToken(true)}>
              Use an API token instead
            </button>
          )}
        </div>
      )}

      {connected && (
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <CircleCheck className="mt-0.5 h-4 w-4 text-primary" />
            <div>
              <p className="text-sm font-medium">
                Connected to{" "}
                <a href={settings?.site_url} target="_blank" rel="noreferrer" className="underline-offset-4 hover:underline">
                  {settings?.site_url?.replace("https://", "")}
                </a>
                {settings?.auth_type === "token" && settings?.email ? ` as ${settings.email}` : ""}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {settings?.last_synced_at
                  ? `Status last synced ${new Date(settings.last_synced_at).toLocaleString()} · every 2 minutes`
                  : "Status syncs every 2 minutes"}
              </p>
              {settings?.last_error && <p className="mt-1 text-xs text-destructive">Last sync failed: {settings.last_error}</p>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {oauth && (
              <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => void connectWithJira()}>
                <LogIn /> Reconnect
              </Button>
            )}
            <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => void sync()}>
              <RefreshCw className={busy === "sync" ? "animate-spin" : ""} /> Sync now
            </Button>
            <Button variant="destructive" size="sm" disabled={busy !== null} onClick={() => void disconnect()}>
              <Unplug /> Disconnect
            </Button>
          </div>
        </div>
      )}

      {connected && projects && (
        <div className="space-y-4 rounded-xl border bg-card p-4">
          <div>
            <p className="text-sm font-medium">Projects</p>
            <p className="text-xs text-muted-foreground">
              Tasks tagged with a Charcha project go to its Jira project; everything else goes to the default project.
            </p>
          </div>
          <Field label="Default Jira project">
            <select className="h-8 w-full max-w-sm rounded-lg border bg-card px-2 text-sm" value={defaultProject} onChange={(e) => setDefaultProject(e.target.value)}>
              <option value="">Choose a project</option>
              {projects.jira.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name} ({p.key})
                </option>
              ))}
            </select>
          </Field>
          {projects.charcha.length > 0 && (
            <div className="divide-y rounded-lg border">
              {projects.charcha.map((project) => (
                <div key={project.id} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="flex items-center gap-2 text-sm">
                    <Link2 className="h-3.5 w-3.5 text-muted-foreground" />
                    {project.name}
                  </span>
                  <select
                    className="h-8 w-56 rounded-lg border bg-card px-2 text-sm"
                    value={projectMap[project.id] ?? ""}
                    onChange={(e) => setProjectMap({ ...projectMap, [project.id]: e.target.value })}
                  >
                    <option value="">{defaultLabel}</option>
                    {projects.jira.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.name} ({p.key})
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
          <Field label="Send tasks automatically">
            <select
              className="h-8 w-full max-w-sm rounded-lg border bg-card px-2 text-sm"
              value={autoSend}
              onChange={(e) => setAutoSend(e.target.value as "off" | "mapped" | "all")}
            >
              <option value="off">Off — people click Send to Jira</option>
              <option value="mapped">Only tasks in a mapped Charcha project</option>
              <option value="all">Every open task, when a meeting&apos;s notes are ready</option>
            </select>
          </Field>
          <Button disabled={!defaultProject || busy !== null} onClick={() => void saveProjects()}>
            {busy === "projects" ? <RefreshCw className="animate-spin" /> : <CircleCheck />}
            Save projects
          </Button>
        </div>
      )}

      {connected && settings?.default_project_key && <JiraPeopleSection />}
      {connected && settings?.default_project_key && <JiraActivitySection siteUrl={settings?.site_url ?? null} />}

      {connected && settings?.auth_type === "token" && !showToken && (
        <button type="button" className="text-xs text-muted-foreground underline-offset-4 hover:underline" onClick={() => setShowToken(true)}>
          Change the API token or account
        </button>
      )}

      {tokenFormVisible && (
        <div className="space-y-4 rounded-xl border bg-card p-4">
          <p className="flex items-center gap-2 text-sm font-medium">
            <KeyRound className="h-4 w-4" /> Connect with an API token
          </p>
          <ol className="list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
            <li>Pick the Jira account issues should be created by (a shared one works best).</li>
            <li>
              Signed in as that account, create an API token at{" "}
              <a href={TOKEN_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline underline-offset-4">
                id.atlassian.com <ExternalLink className="h-3 w-3" />
              </a>
              .
            </li>
            <li>Paste it below with the account&apos;s email and your Jira address.</li>
          </ol>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Jira address">
              <Input placeholder="yourcompany.atlassian.net" value={tokenForm.site_url} onChange={(e) => setTokenForm({ ...tokenForm, site_url: e.target.value })} />
            </Field>
            <Field label="Account email">
              <Input type="email" name="jira-account-email" autoComplete="off" value={tokenForm.email} onChange={(e) => setTokenForm({ ...tokenForm, email: e.target.value })} />
            </Field>
            <Field label={connected && settings?.auth_type === "token" ? "API token (leave blank to keep)" : "API token"}>
              {/* new-password: browsers ignore autoComplete="off" on password
                  fields and fill the saved Charcha login into it. */}
              <Input type="password" name="jira-api-token" autoComplete="new-password" placeholder="Starts with ATATT…" value={tokenForm.api_token} onChange={(e) => setTokenForm({ ...tokenForm, api_token: e.target.value })} />
            </Field>
            <Field label="Default Jira project key">
              <Input placeholder="e.g. MEM" value={tokenForm.default_project_key} onChange={(e) => setTokenForm({ ...tokenForm, default_project_key: e.target.value.toUpperCase() })} />
            </Field>
          </div>
          <div className="flex gap-2">
            <Button
              disabled={
                !tokenForm.site_url.trim() || !tokenForm.email.trim() || !tokenForm.default_project_key.trim() ||
                (!(connected && settings?.auth_type === "token") && !tokenForm.api_token.trim()) || busy !== null
              }
              onClick={() => void saveToken()}
            >
              {busy === "token" ? <RefreshCw className="animate-spin" /> : <Link2 />}
              {connected ? "Save" : "Connect"}
            </Button>
            {(oauth || connected) && (
              <Button variant="ghost" onClick={() => setShowToken(false)}>
                Cancel
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}


const MATCH_LABELS: Record<string, string> = { email: "matched by email", name: "matched by name", manual: "set by an admin" };

/** Who each Charcha person is in Jira. Drives assignee <-> owner and comment
 * authors; Jira Free hides most emails, so names do most of the matching. */
function JiraPeopleSection() {
  const [data, setData] = useState<JiraPeople | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    api.adminJiraPeople().then(setData).catch((cause) => setError(message(cause, "Couldn't load Jira people")));
  }, []);

  async function choose(userId: string, value: string) {
    setSaving(userId);
    setError(null);
    try {
      setData(value === "auto" ? await api.resetJiraPerson(userId) : await api.setJiraPerson(userId, value === "none" ? null : value));
    } catch (cause) {
      setError(message(cause, "Couldn't save"));
    } finally {
      setSaving(null);
    }
  }

  const unmatched = data?.people.filter((p) => !p.account_id && p.matched_by !== "manual").length ?? 0;
  return (
    <div className="space-y-3 rounded-xl border bg-card p-4">
      <div>
        <p className="flex items-center gap-2 text-sm font-medium">
          <Users className="h-4 w-4" /> People
        </p>
        <p className="text-xs text-muted-foreground">
          Who each person is in Jira, so a task&apos;s owner becomes the issue&apos;s assignee (and back), and Jira comments show the right
          name. Matched automatically by email or exact name; pick by hand where that fails.
          {unmatched > 0 && ` ${unmatched} not matched yet.`}
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!data && !error && <Skeleton className="h-40 w-full" />}
      {data && (
        <div className="divide-y rounded-lg border">
          {data.people.map((person) => (
            <div key={person.user_id} className="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="truncate text-sm">{person.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {person.email}
                  {person.matched_by && person.account_id ? ` · ${MATCH_LABELS[person.matched_by]}` : ""}
                </p>
              </div>
              <select
                className="h-8 w-full rounded-lg border bg-card px-2 text-sm sm:w-64"
                disabled={saving === person.user_id}
                value={person.matched_by === "manual" ? person.account_id ?? "none" : person.account_id ?? ""}
                onChange={(e) => void choose(person.user_id, e.target.value || "auto")}
              >
                <option value="">{person.account_id ? "Automatic" : "Not matched — choose"}</option>
                {data.jira_users.map((u) => (
                  <option key={u.account_id} value={u.account_id}>
                    {u.name}
                    {u.email ? ` (${u.email})` : ""}
                  </option>
                ))}
                <option value="none">Not in Jira</option>
                {person.matched_by === "manual" && <option value="auto">Reset to automatic</option>}
              </select>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const FIELD_LABELS: Record<string, string> = {
  description: "text",
  owner: "owner",
  due_date: "due date",
  priority: "priority",
  status: "status",
};

/** What's linked, what Jira changed lately, and what's failing. */
function JiraActivitySection({ siteUrl }: { siteUrl: string | null }) {
  const [data, setData] = useState<JiraActivity | null>(null);
  const jira = { connected: true, site_url: siteUrl };

  useEffect(() => {
    api.adminJiraActivity().then(setData).catch(() => setData(null));
  }, []);

  if (!data) return null;
  return (
    <div className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">Activity</p>
        <p className="text-xs text-muted-foreground">
          {data.linked} task{data.linked === 1 ? "" : "s"} in Jira · {data.open_linked} open
        </p>
      </div>

      {data.problems.length > 0 && (
        <div className="space-y-1.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
            <AlertTriangle className="h-3.5 w-3.5" /> Sync problems
          </p>
          {data.problems.map((p) => (
            <div key={p.task_id} className="rounded-lg border border-destructive/30 px-3 py-2 text-xs">
              <a href={`/meetings/${p.meeting_id}?tab=actions`} className="font-medium hover:underline">
                {p.description}
              </a>
              {p.issue_key && <span className="text-muted-foreground"> · {p.issue_key}</span>}
              <p className="mt-0.5 text-muted-foreground">{p.error}</p>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1.5">
        <p className="text-xs font-medium text-muted-foreground">Latest changes made in Jira</p>
        {data.recent.length === 0 ? (
          <p className="text-xs text-muted-foreground">None yet. Edits made in Jira show up here within two minutes.</p>
        ) : (
          <div className="divide-y rounded-lg border">
            {data.recent.map((r, i) => {
              const url = jiraIssueUrl(jira, r.issue_key);
              return (
                <div key={`${r.task_id}-${i}`} className="flex items-start gap-2 px-3 py-2 text-xs">
                  <ArrowDownLeft className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">
                      {url ? (
                        <a href={url} target="_blank" rel="noreferrer" className="font-medium hover:underline">
                          {r.issue_key}
                        </a>
                      ) : (
                        <span className="font-medium">{r.issue_key ?? "Unlinked"}</span>
                      )}{" "}
                      {FIELD_LABELS[r.field] ?? r.field}: <span className="text-muted-foreground">{r.old_value || "—"}</span> →{" "}
                      {r.new_value || "—"}
                    </p>
                    <p className="truncate text-muted-foreground">{r.description}</p>
                  </div>
                  <span className="shrink-0 text-muted-foreground">{new Date(r.changed_at).toLocaleString()}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
