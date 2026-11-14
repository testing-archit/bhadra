"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { api, ApiError, RecycleBinItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ArchiveRestore, Building2, CheckCircle2, ExternalLink, Monitor, Moon, RotateCcw, Sheet, Sun, Trash2 } from "lucide-react";
import { useTheme, type ThemePreference } from "@/lib/theme";
import { PageHeader } from "@/components/page-header";
import { CalendarSettings } from "@/components/calendar-settings";
import { JiraSettingsCard } from "@/components/jira-task-button";
import { EmailSettings, PasswordSettings } from "@/components/email-settings";
import { initialsFor } from "@/components/shell/sidebar";
import { cn } from "@/lib/utils";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";

const SUGGESTIONS = ["Engineering", "Sales", "Marketing", "Design", "Operations", "Founders"];
const ROLE_LABELS: Record<string, string> = { super_admin: "Super admin", admin: "Admin", team_admin: "Team admin", member: "Member" };
const THEMES: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match system", icon: Monitor },
];

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const { preference, setPreference } = useTheme();
  const [department, setDepartment] = useState(() => user?.department ?? "");
  const [departmentBusy, setDepartmentBusy] = useState(false);
  const [departmentMessage, setDepartmentMessage] = useState<string | null>(null);
  const [spreadsheetId, setSpreadsheetId] = useState("");
  const [tasksTab, setTasksTab] = useState("Tasks");
  const [notesTab, setNotesTab] = useState("Meeting Notes");
  const [sheetsLoading, setSheetsLoading] = useState(true);
  const [sheetsBusy, setSheetsBusy] = useState(false);
  const [sheetsError, setSheetsError] = useState<string | null>(null);
  const [sheetsSaved, setSheetsSaved] = useState(false);
  const [recycleItems, setRecycleItems] = useState<RecycleBinItem[] | null>(null);
  const [recycleError, setRecycleError] = useState<string | null>(null);
  const [recycleBusy, setRecycleBusy] = useState<string | null>(null);
  const [permanentTarget, setPermanentTarget] = useState<RecycleBinItem | null>(null);

  useEffect(() => {
    api.getGoogleSheetsSettings().then(
      (settings) => {
        setSpreadsheetId(settings.spreadsheet_id ?? "");
        setTasksTab(settings.tasks_tab);
        setNotesTab(settings.notes_tab);
        setSheetsLoading(false);
      },
      (error) => {
        setSheetsError(error instanceof ApiError ? error.message : "Could not load Google Sheets settings");
        setSheetsLoading(false);
      }
    );
  }, []);

  useEffect(() => {
    api.listRecycleBin().then(setRecycleItems).catch((error) => setRecycleError(error instanceof ApiError ? error.message : "Could not load the Recycle Bin"));
  }, []);

  async function restoreItem(item: RecycleBinItem) {
    setRecycleBusy(item.id);
    setRecycleError(null);
    try {
      await api.restoreRecycleItem(item.type, item.id);
      setRecycleItems((current) => current?.filter((entry) => entry.id !== item.id) ?? null);
    } catch (error) {
      setRecycleError(error instanceof ApiError ? error.message : "The item could not be restored");
    } finally {
      setRecycleBusy(null);
    }
  }

  async function permanentlyDeleteItem() {
    if (!permanentTarget) return;
    setRecycleBusy(permanentTarget.id);
    setRecycleError(null);
    try {
      await api.permanentlyDeleteRecycleItem(permanentTarget.type, permanentTarget.id);
      setRecycleItems((current) => current?.filter((entry) => entry.id !== permanentTarget.id) ?? null);
      setPermanentTarget(null);
    } catch (error) {
      setRecycleError(error instanceof ApiError ? error.message : "The item could not be permanently deleted");
    } finally {
      setRecycleBusy(null);
    }
  }

  async function saveDepartment(event: React.FormEvent) {
    event.preventDefault();
    if (!department.trim()) return;
    setDepartmentBusy(true);
    setDepartmentMessage(null);
    try {
      await api.updateDepartment(department.trim());
      await refreshUser();
      setDepartmentMessage("Department saved.");
    } catch (error) {
      setDepartmentMessage(error instanceof ApiError ? error.message : "Failed to save department");
    } finally {
      setDepartmentBusy(false);
    }
  }

  async function saveGoogleSheets(event: React.FormEvent) {
    event.preventDefault();
    setSheetsBusy(true);
    setSheetsError(null);
    setSheetsSaved(false);
    try {
      const settings = await api.updateGoogleSheetsSettings({
        spreadsheet_id: spreadsheetId.trim() || null,
        tasks_tab: tasksTab.trim() || "Tasks",
        notes_tab: notesTab.trim() || "Meeting Notes",
      });
      setSpreadsheetId(settings.spreadsheet_id ?? "");
      setTasksTab(settings.tasks_tab);
      setNotesTab(settings.notes_tab);
      setSheetsSaved(true);
    } catch (error) {
      setSheetsError(error instanceof ApiError ? error.message : "Failed to save Google Sheets settings");
    } finally {
      setSheetsBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader title="Settings" description="Your profile, how Charcha looks, and the integrations shared with the Chrome extension." />

      {user && (
        <Card>
          <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-center">
            <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-primary text-lg font-semibold text-primary-foreground">
              {initialsFor(user.name, user.email)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-lg font-semibold">{user.name || user.email.split("@")[0]}</p>
              <p className="truncate text-sm text-muted-foreground">{user.email}</p>
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:text-right">
              <dt className="text-muted-foreground sm:order-1">Role</dt>
              <dd className="font-medium sm:order-2">{ROLE_LABELS[user.role] || user.role}</dd>
              <dt className="text-muted-foreground sm:order-3">Team</dt>
              <dd className="font-medium sm:order-4">{user.team_name || "Not assigned"}</dd>
              <dt className="text-muted-foreground sm:order-5">Member since</dt>
              <dd className="font-medium sm:order-6">{new Date(user.created_at).toLocaleDateString(undefined, { month: "short", year: "numeric" })}</dd>
            </dl>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Appearance</CardTitle>
          <CardDescription>Dark mode follows your operating system unless you pick one here.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Theme">
            {THEMES.map((theme) => (
              <button
                key={theme.value}
                type="button"
                role="radio"
                aria-checked={preference === theme.value}
                onClick={() => setPreference(theme.value)}
                className={cn(
                  "flex flex-col items-center gap-2 rounded-xl border p-4 text-sm transition-colors hover:bg-muted",
                  preference === theme.value && "border-primary bg-primary/5 font-medium text-primary hover:bg-primary/5",
                )}
              >
                <theme.icon className="size-5" />
                {theme.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <CalendarSettings />

      <EmailSettings />

      <PasswordSettings />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Building2 className="h-4 w-4" /> Department</CardTitle>
          <CardDescription>
            Controls which meetings, tasks, decisions, and memory answers are visible to your account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={saveDepartment} className="flex flex-col gap-3">
            <Input value={department} onChange={(event) => setDepartment(event.target.value)} placeholder="e.g. Engineering" list="department-suggestions" />
            <datalist id="department-suggestions">{SUGGESTIONS.map((item) => <option key={item} value={item} />)}</datalist>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((item) => (
                <button type="button" key={item} onClick={() => setDepartment(item)} className="rounded-full border bg-card px-3 py-1 text-xs transition-colors hover:bg-accent hover:text-accent-foreground">{item}</button>
              ))}
            </div>
            {departmentMessage && <p className="text-sm text-muted-foreground">{departmentMessage}</p>}
            <Button type="submit" className="self-start" disabled={departmentBusy || !department.trim()}>{departmentBusy ? "Saving..." : "Save department"}</Button>
          </form>
        </CardContent>
      </Card>

      <JiraSettingsCard isAdmin={!!user?.is_admin} />

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base"><Sheet className="h-4 w-4 text-success" /> Google Sheets export</CardTitle>
              <CardDescription className="mt-1">
                When a notetaker meeting finishes, the Charcha Chrome extension adds its tasks and summary to this spreadsheet using your Google sign-in.
              </CardDescription>
            </div>
            <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">Optional</span>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={saveGoogleSheets} className="flex flex-col gap-4">
            <div className="grid gap-2">
              <Label htmlFor="spreadsheet-id">Spreadsheet URL or ID</Label>
              <Input id="spreadsheet-id" value={spreadsheetId} onChange={(event) => setSpreadsheetId(event.target.value)} disabled={sheetsLoading} placeholder="https://docs.google.com/spreadsheets/d/..." />
              <p className="text-xs text-muted-foreground">Leave empty to keep all data in Charcha without exporting to Sheets.</p>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label htmlFor="tasks-tab">Tasks tab</Label><Input id="tasks-tab" value={tasksTab} onChange={(event) => setTasksTab(event.target.value)} disabled={sheetsLoading} /></div>
              <div className="grid gap-2"><Label htmlFor="notes-tab">Meeting notes tab</Label><Input id="notes-tab" value={notesTab} onChange={(event) => setNotesTab(event.target.value)} disabled={sheetsLoading} /></div>
            </div>
            <div className="rounded-md border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
              Turn the copy on or off from the extension's settings. Charcha stays the source of truth; the spreadsheet is a copy for people who live in Sheets.
            </div>
            {sheetsError && <p className="text-sm text-destructive">{sheetsError}</p>}
            {sheetsSaved && <p className="flex items-center gap-1.5 text-sm text-foreground"><CheckCircle2 className="h-4 w-4" /> Shared integration settings saved.</p>}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={sheetsLoading || sheetsBusy}>{sheetsBusy ? "Saving..." : "Save Google Sheets settings"}</Button>
              {spreadsheetId && <a href={`https://docs.google.com/spreadsheets/d/${spreadsheetId}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">Open spreadsheet <ExternalLink className="h-3.5 w-3.5" /></a>}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><ArchiveRestore className="h-4 w-4 text-primary" /> Recycle Bin</CardTitle>
          <CardDescription>Restore incorrect deletions or permanently remove them. Deleted records disappear from Company Memory immediately.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {recycleError && <p className="text-sm text-destructive">{recycleError}</p>}
          {recycleItems === null && !recycleError && <p className="text-sm text-muted-foreground">Loading deleted records…</p>}
          {recycleItems?.length === 0 && <div className="rounded-lg border border-dashed px-4 py-8 text-center"><ArchiveRestore className="mx-auto h-7 w-7 text-muted-foreground" /><p className="mt-2 text-sm font-medium">Nothing to restore</p><p className="mt-1 text-xs text-muted-foreground">Deleted meetings and extracted records will appear here.</p></div>}
          {recycleItems?.map((item) => (
            <div key={`${item.type}-${item.id}`} className="grid grid-cols-[4px_1fr_auto] items-stretch gap-3 overflow-hidden rounded-lg border bg-card pr-3">
              <div className="bg-primary/55" />
              <div className="min-w-0 py-3"><div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{item.type}</span><p className="truncate text-sm font-medium">{item.title}</p></div><p className="mt-1 truncate text-xs text-muted-foreground">{item.detail} · deleted {new Date(item.deleted_at).toLocaleString()}</p></div>
              <div className="flex items-center gap-1 py-3"><Button size="sm" variant="outline" disabled={recycleBusy === item.id} onClick={() => void restoreItem(item)}><RotateCcw className="h-3.5 w-3.5" /> Restore</Button><Button size="icon-sm" variant="ghost" className="text-muted-foreground hover:text-destructive" disabled={recycleBusy === item.id} onClick={() => setPermanentTarget(item)} aria-label={`Permanently delete ${item.title}`}><Trash2 className="h-3.5 w-3.5" /></Button></div>
            </div>
          ))}
        </CardContent>
      </Card>

      <DeleteConfirmationDialog open={!!permanentTarget} onOpenChange={(open) => !open && !recycleBusy && setPermanentTarget(null)} title={`Permanently delete “${permanentTarget?.title ?? "item"}”?`} description="This cannot be undone. The record and any remaining search data will be removed permanently." confirmLabel="Delete permanently" busy={!!permanentTarget && recycleBusy === permanentTarget.id} onConfirm={permanentlyDeleteItem} />
    </div>
  );
}
