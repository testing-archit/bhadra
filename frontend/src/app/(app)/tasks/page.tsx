"use client";

import { type KeyboardEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CalendarPlus,
  Check,
  Copy,
  CopyCheck,
  Download,
  FolderKanban,
  Hourglass,
  ListChecks,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError, LEARNED_CORRECTIONS_EVENT, type TaskListItem } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { STATUS_LABELS } from "@/lib/labels";
import { downloadBlob } from "@/lib/media-time";
import {
  compareByUrgency,
  daysSince,
  DUE_BUCKETS,
  dueBucket,
  type DueBucket,
  formatDue,
  isMyTask,
  isStale,
  possibleDuplicates,
  reminderText,
  snoozedDueDate,
  STALE_DAYS,
  tasksToCsv,
  urgency,
} from "@/lib/tasks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { TaskEditDialog, type EditableTask } from "@/components/task-edit-dialog";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";
import { VerificationBadge } from "@/components/verification-badge";
import { JiraTaskButton, useJiraStatus } from "@/components/jira-task-button";
import { TaskWorkspace, TaskWaitingStrip, type TaskQuickUpdate } from "@/components/task-workspace";

const STATUSES = ["pending", "in_progress", "done"] as const;
type View = "workspace" | "list" | "board";
/** Whose tasks: yours (the default), ones you're waiting on, nobody's, or everything you can see. */
type Scope = "mine" | "waiting" | "unassigned" | "all";
type EditFields = { description: string; owner: string; deadline: string; due_date: string; priority: string; status: string };
type PendingDelete = { ids: string[]; label: string };

const VIEW_KEY = "wilco.tasks.layout.v3";
const DISMISSED_KEY = "charcha.tasks.notDuplicates";
const DONE_SHOWN = 8;
const selectClass = "h-8 [@media(pointer:coarse)]:min-h-11 rounded-lg border bg-background px-2.5 text-sm text-foreground";

const SCOPES: { value: Scope; label: string; hint: string }[] = [
  { value: "mine", label: "My tasks", hint: "Assigned to you" },
  { value: "waiting", label: "Waiting on others", hint: "From your meetings, owned by someone else" },
  { value: "unassigned", label: "Unassigned", hint: "Nobody owns these yet" },
  { value: "all", label: "Everything", hint: "Every task you can see" },
];

function priorityTone(priority: string | null) {
  if (priority === "High") return "bg-destructive/10 text-destructive";
  if (priority === "Medium") return "bg-warning/15 text-foreground";
  return "bg-muted text-muted-foreground";
}

/** Priority as a tinted pill with a dot and its word, so colour is never
 * the only cue. Low priority shows nothing. */
function priorityPill(priority: string | null) {
  if (priority === "High") return "bg-tint-rose text-tint-rose-foreground";
  if (priority === "Medium") return "bg-tint-peach text-tint-peach-foreground";
  return null;
}

function statusTone(status: string) {
  if (status === "done") return "bg-success/15 text-foreground";
  if (status === "in_progress") return "bg-primary/12 text-primary";
  return "bg-muted text-muted-foreground";
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).map((part) => part[0]).slice(0, 2).join("").toUpperCase();
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private windows can refuse storage; the preference just isn't kept.
  }
}

function pairKey(a: TaskListItem, b: TaskListItem) {
  return [a.id, b.id].sort().join(":");
}

export default function TasksPage() {
  const jira = useJiraStatus();
  const { user } = useAuth();
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<View>("workspace");
  const [showFilters, setShowFilters] = useState(false);
  const [scope, setScope] = useState<Scope>("mine");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("open");
  const [dueFilter, setDueFilter] = useState<DueBucket | "">("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [meetingFilter, setMeetingFilter] = useState("");
  const [editingTask, setEditingTask] = useState<TaskListItem | null>(null);
  const [addingTask, setAddingTask] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkOwner, setBulkOwner] = useState("");
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [notDuplicates, setNotDuplicates] = useState<Set<string>>(new Set());

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlView = params.get("view");
    // The workspace replaces Focus; existing list/board preferences and links still work.
    const savedView = readStorage(VIEW_KEY) ?? readStorage("wilco.tasks.layout.v2");
    if (urlView === "focus" || urlView === "workspace") setView("workspace");
    else if (urlView === "list" || urlView === "board") setView(urlView);
    else if (savedView === "list" || savedView === "board" || savedView === "workspace") setView(savedView);
    const urlScope = params.get("scope");
    if (urlScope && SCOPES.some((item) => item.value === urlScope)) setScope(urlScope as Scope);
    else if (params.get("owner") === "all") setScope("all");
    if (params.get("due") === "overdue") setDueFilter("overdue");
    if (params.get("new") === "1") setAddingTask(true);
    try {
      setNotDuplicates(new Set(JSON.parse(readStorage(DISMISSED_KEY) ?? "[]") as string[]));
    } catch {
      setNotDuplicates(new Set());
    }
    // ?task=<id> (from a notification) opens that task.
    const openId = params.get("task");
    api
      .listTasks()
      .then((list) => {
        setTasks(list);
        const opened = openId ? list.find((task) => task.id === openId) : undefined;
        if (opened) setEditingTask(opened);
      })
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Tasks could not be loaded."));
  }, []);

  // A fixed misheard name also fixes the meeting's other tasks: show them.
  useEffect(() => {
    const reload = () => void api.listTasks().then(setTasks).catch(() => undefined);
    window.addEventListener(LEARNED_CORRECTIONS_EVENT, reload);
    return () => window.removeEventListener(LEARNED_CORRECTIONS_EVENT, reload);
  }, []);

  function setUrlParam(name: string, value: string | null) {
    const url = new URL(window.location.href);
    if (value) url.searchParams.set(name, value);
    else url.searchParams.delete(name);
    url.searchParams.delete("owner");
    window.history.replaceState(null, "", url);
  }

  function changeView(next: View) {
    setView(next);
    writeStorage(VIEW_KEY, next);
    setSelectedIds(new Set());
    setUrlParam("view", next === "workspace" ? null : next);
  }

  function changeScope(next: Scope) {
    setScope(next);
    setOwnerFilter("");
    setSelectedIds(new Set());
    setUrlParam("scope", next === "mine" ? null : next);
  }

  const mineOf = (task: TaskListItem) => isMyTask(task, user);

  const inScope = useMemo(() => {
    if (!tasks) return null;
    return tasks.filter((task) => {
      if (scope === "mine") return mineOf(task);
      if (scope === "waiting") return !!task.delegated;
      if (scope === "unassigned") return !task.owner?.trim();
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, scope, user]);

  const options = useMemo(() => {
    const unique = (values: (string | null | undefined)[]) =>
      Array.from(new Set(values.filter(Boolean) as string[])).sort((a, b) => a.localeCompare(b));
    const scoped = inScope ?? [];
    return {
      owners: unique(scoped.map((task) => task.owner)),
      projects: unique(scoped.map((task) => task.project)),
      meetings: unique(scoped.map((task) => task.meeting_title)),
      allOwners: unique((tasks ?? []).map((task) => task.owner)),
    };
  }, [inScope, tasks]);

  const filtersActive = !!(query.trim() || dueFilter || ownerFilter || priorityFilter || projectFilter || meetingFilter || (view !== "board" && statusFilter !== "open" && statusFilter !== "done"));

  function clearFilters() {
    setQuery("");
    setDueFilter("");
    setOwnerFilter("");
    setPriorityFilter("");
    setProjectFilter("");
    setMeetingFilter("");
    setStatusFilter("open");
  }

  const filtered = useMemo(() => {
    if (!inScope) return null;
    const q = query.trim().toLowerCase();
    return inScope
      .filter((task) => {
        // The board shows every status; other layouts can switch to completed work.
        if (view !== "board") {
          if (statusFilter === "open" && task.status === "done") return false;
          if (statusFilter !== "open" && statusFilter !== "" && task.status !== statusFilter) return false;
        }
        if (dueFilter && dueBucket(task) !== dueFilter) return false;
        if (ownerFilter && task.owner !== ownerFilter) return false;
        if (priorityFilter && task.priority !== priorityFilter) return false;
        if (projectFilter && task.project !== projectFilter) return false;
        if (meetingFilter && task.meeting_title !== meetingFilter) return false;
        if (q && !`${task.description} ${task.owner ?? ""} ${task.meeting_title} ${task.project ?? ""}`.toLowerCase().includes(q)) return false;
        return true;
      })
      .sort((a, b) => urgency(b).score - urgency(a).score || compareByUrgency(a, b));
  }, [inScope, query, statusFilter, dueFilter, ownerFilter, priorityFilter, projectFilter, meetingFilter, view]);

  function patchTasks(updates: Partial<TaskListItem> & { id: string }) {
    setTasks((current) => current?.map((task) => (task.id === updates.id ? { ...task, ...updates } : task)) ?? null);
  }

  async function setStatus(task: TaskListItem, status: string) {
    patchTasks({ id: task.id, status });
    try {
      const updated = await api.updateTaskStatus(task.id, status);
      patchTasks({ id: task.id, status: updated.status, updated_at: updated.updated_at, verified_at: updated.verified_at });
    } catch {
      patchTasks({ id: task.id, status: task.status });
      setError("The status could not be saved. Try again.");
    }
  }

  async function updateQuickTask(task: TaskListItem, fields: TaskQuickUpdate) {
    // Commit after success so a rejected action keeps the current card in place.
    const updated = await api.updateTask(task.id, fields);
    patchTasks({ ...updated, ...(fields.owner !== undefined ? { mine: undefined, delegated: undefined } : {}) });
    if (fields.owner !== undefined) {
      // Ownership affects both Mine and Waiting; refresh the server-computed relationship.
      await api.listTasks().then(setTasks).catch(() => undefined);
    }
  }

  async function snooze(task: TaskListItem) {
    const due = snoozedDueDate(task);
    try {
      const updated = await api.updateTask(task.id, { due_date: due });
      patchTasks({ id: task.id, due_date: updated.due_date, updated_at: updated.updated_at });
      setNotice(`“${task.description}” is now due ${formatDue({ ...task, due_date: updated.due_date })}.`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The new due date wasn't saved.");
    }
  }

  async function saveTaskEdits(task: TaskListItem, fields: EditFields) {
    const updated = await api.updateTask(task.id, {
      description: fields.description,
      owner: fields.owner,
      deadline: fields.deadline,
      priority: fields.priority,
      status: fields.status,
      ...(fields.due_date ? { due_date: fields.due_date } : { clear_due_date: true }),
    });
    patchTasks({
      id: task.id,
      description: updated.description,
      owner: updated.owner,
      deadline: updated.deadline,
      due_date: updated.due_date,
      priority: updated.priority,
      status: updated.status,
      updated_at: updated.updated_at,
      verified_at: updated.verified_at,
    });
    // Reassigning changes whose task it is; the server knows best.
    if (updated.owner !== task.owner) void api.listTasks().then(setTasks).catch(() => undefined);
  }

  async function createTask(fields: { description: string; owner: string; deadline: string; due_date: string; priority: string }) {
    const created = await api.createTask({
      description: fields.description,
      owner: fields.owner || undefined,
      deadline: fields.deadline || undefined,
      due_date: fields.due_date || undefined,
      priority: fields.priority || undefined,
    });
    setTasks((current) => [created, ...(current ?? [])]);
  }

  async function addSubtask(parentId: string, description: string) {
    const created = await api.createTask({ description, parent_task_id: parentId });
    setTasks((current) => [created, ...(current ?? [])]);
  }

  function askDelete(list: TaskListItem[]) {
    if (!list.length) return;
    setPendingDelete({
      ids: list.map((task) => task.id),
      label: list.length === 1 ? `“${list[0].description}”` : `These ${list.length} tasks`,
    });
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      const { deleted, failed } =
        pendingDelete.ids.length === 1
          ? await api.deleteTask(pendingDelete.ids[0]).then(() => ({ deleted: pendingDelete.ids, failed: {} as Record<string, string> }))
          : await api.deleteTasks(pendingDelete.ids);
      const gone = new Set(deleted);
      setTasks((current) => current?.filter((task) => !gone.has(task.id)) ?? null);
      setSelectedIds((current) => new Set([...current].filter((id) => !gone.has(id))));
      if (editingTask && gone.has(editingTask.id)) setEditingTask(null);
      const failures = Object.keys(failed).length;
      if (failures) setError(`${failures} task${failures === 1 ? "" : "s"} couldn't be deleted — you need access to the meeting a task came from.`);
      if (deleted.length) setNotice(`${deleted.length === 1 ? "Task" : `${deleted.length} tasks`} moved to the Recycle Bin (Settings) — restore from there if needed.`);
      setPendingDelete(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The task could not be deleted.");
    } finally {
      setDeleting(false);
    }
  }

  async function sendSelectedToJira() {
    const ids = (tasks ?? []).filter((task) => selectedIds.has(task.id) && !task.jira_issue_key).map((task) => task.id);
    if (!ids.length) return;
    setBulkBusy(true);
    setError(null);
    try {
      const { created, failed } = await api.sendTasksToJira(ids);
      for (const [id, key] of Object.entries(created)) patchTasks({ id, jira_issue_key: key, jira_error: null });
      const failures = Object.values(failed);
      if (failures.length) setError(`${failures.length} task${failures.length === 1 ? "" : "s"} couldn't be sent to Jira: ${failures[0]}`);
      setSelectedIds(new Set(Object.keys(failed)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Couldn't send the tasks to Jira");
    } finally {
      setBulkBusy(false);
    }
  }

  const selectedUnsent = (tasks ?? []).filter((task) => selectedIds.has(task.id) && !task.jira_issue_key).length;

  async function applyBulk(fields: { status?: string; owner?: string }) {
    setBulkBusy(true);
    try {
      // Each task saves on its own: one failure mustn't hide the others' changes.
      const ids = Array.from(selectedIds);
      const results = await Promise.allSettled(ids.map((id) => api.updateTask(id, fields)));
      const failedIds = new Set<string>();
      let firstError: unknown = null;
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          const updated = result.value;
          patchTasks({ id: updated.id, status: updated.status, owner: updated.owner, updated_at: updated.updated_at, verified_at: updated.verified_at });
        } else {
          failedIds.add(ids[index]);
          firstError ??= result.reason;
        }
      });
      // What failed stays selected, ready to try again.
      setSelectedIds(failedIds);
      setBulkOwner("");
      if (failedIds.size) {
        setError(
          `${failedIds.size} task${failedIds.size === 1 ? "" : "s"} couldn't be updated` +
            (firstError instanceof ApiError ? `: ${firstError.message}` : "."),
        );
      }
      if (fields.owner) void api.listTasks().then(setTasks).catch(() => undefined);
    } finally {
      setBulkBusy(false);
    }
  }

  function dismissDuplicate(a: TaskListItem, b: TaskListItem) {
    setNotDuplicates((current) => {
      const next = new Set(current).add(pairKey(a, b));
      writeStorage(DISMISSED_KEY, JSON.stringify([...next]));
      return next;
    });
  }

  async function copyReminder(owner: string, list: TaskListItem[]) {
    try {
      await navigator.clipboard.writeText(reminderText(owner, list));
      setNotice(`A reminder for ${owner} is on your clipboard — paste it into chat or email.`);
    } catch {
      setError("Your browser didn't allow copying to the clipboard.");
    }
  }

  function exportCsv() {
    if (!filtered) return;
    downloadBlob(new Blob([tasksToCsv(filtered)], { type: "text/csv;charset=utf-8" }), `wilco-tasks-${new Date().toISOString().slice(0, 10)}.csv`);
  }

  const allSelected = !!filtered?.length && filtered.every((task) => selectedIds.has(task.id));
  const selectedTasks = (tasks ?? []).filter((task) => selectedIds.has(task.id));
  const ownerLabel = (task: TaskListItem) => (mineOf(task) ? "You" : task.owner || "Unassigned");
  const scopeInfo = SCOPES.find((item) => item.value === scope)!;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-[1.75rem] leading-tight font-bold">Tasks</h1>
        <Button onClick={() => setAddingTask(true)}><Plus data-icon="inline-start" /> Add task</Button>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 sm:flex sm:flex-wrap">
        <label className="flex min-w-0 items-center gap-2">
          <span className="sr-only">Whose tasks</span>
          <select aria-label="Whose tasks" value={scope} onChange={(event) => changeScope(event.target.value as Scope)} className={cn(selectClass, "max-w-full")}>
            {SCOPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <div className="relative order-last col-span-3 sm:order-none sm:ml-auto sm:w-60">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a task" className="pl-9" aria-label="Search tasks" />
        </div>
        <label className="flex items-center gap-2">
          <span className="sr-only">Layout</span>
          <select aria-label="Layout" value={view} onChange={(event) => changeView(event.target.value as View)} className={selectClass}>
            <option value="workspace">Cards</option>
            <option value="list">List</option>
            <option value="board">Board</option>
          </select>
        </label>
        <Button variant="outline" aria-expanded={showFilters} aria-controls="task-filters" onClick={() => setShowFilters(!showFilters)}>
          <SlidersHorizontal data-icon="inline-start" /> Filters{filtersActive ? " · on" : ""}
        </Button>
      </div>

      <div id="task-filters" hidden={!showFilters}>
        <div className="flex flex-wrap items-center gap-2">
          <select value={dueFilter} onChange={(event) => setDueFilter(event.target.value as DueBucket | "")} aria-label="Due" className={selectClass}>
            <option value="">Any due date</option>
            {DUE_BUCKETS.map((bucket) => <option key={bucket.value} value={bucket.value}>{bucket.label}</option>)}
          </select>
          {view !== "board" && (
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Status" className={selectClass}>
              <option value="open">Not done</option>
              <option value="">Any status</option>
              {STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
            </select>
          )}
          {scope !== "mine" && scope !== "unassigned" && options.owners.length > 0 && (
            <select value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)} aria-label="Owner" className={selectClass}>
              <option value="">Any owner</option>
              {options.owners.map((owner) => <option key={owner} value={owner}>{owner}</option>)}
            </select>
          )}
          <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)} aria-label="Priority" className={selectClass}>
            <option value="">Any priority</option>
            {["High", "Medium", "Low"].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
          </select>
          {options.projects.length > 0 && (
            <select value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)} aria-label="Project" className={cn(selectClass, "max-w-44")}>
              <option value="">Any project</option>
              {options.projects.map((project) => <option key={project} value={project}>{project}</option>)}
            </select>
          )}
          {options.meetings.length > 1 && (
            <select value={meetingFilter} onChange={(event) => setMeetingFilter(event.target.value)} aria-label="Meeting" className={cn(selectClass, "max-w-52")}>
              <option value="">Any meeting</option>
              {options.meetings.map((meeting) => <option key={meeting} value={meeting}>{meeting}</option>)}
            </select>
          )}
          {filtersActive && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X /> Clear filters
            </Button>
          )}
        </div>

        <Button className="mt-3" variant="ghost" onClick={exportCsv} disabled={!filtered?.length}><Download data-icon="inline-start" /> Export CSV</Button>
      </div>
      {notice && (
        <p role="status" className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
          {notice}
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X className="size-4" /></button>
        </p>
      )}
      {error && (
        <p role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss"><X className="size-4" /></button>
        </p>
      )}

      {!filtered && !error && <Skeleton className="h-80 w-full rounded-xl" />}

      {view !== "workspace" && filtered && filtered.length === 0 && (
        <EmptyState
          icon={ListChecks}
          title={filtersActive ? "No tasks match" : inScope?.length ? "All done here" : scope === "mine" ? "Nothing assigned to you" : "No tasks here"}
          description={
            filtersActive
              ? "Try clearing the filters."
              : scope === "mine"
                ? "Tasks people give you in meetings show up here automatically, or add one yourself."
                : scopeInfo.hint + "."
          }
          action={filtersActive ? <Button variant="outline" onClick={clearFilters}><X /> Clear filters</Button> : <Button onClick={() => setAddingTask(true)}><Plus /> Add task</Button>}
        />
      )}

      {view === "workspace" && filtered && (
        <TaskWorkspace
          key={scope}
          tasks={filtered}
          completedCount={(inScope ?? []).filter((task) => task.status === "done").length}
          showingCompleted={statusFilter === "done"}
          onToggleCompleted={() => setStatusFilter(statusFilter === "done" ? "open" : "done")}
          owners={Array.from(new Set([user?.name || user?.email || "", ...options.allOwners].filter(Boolean)))}
          ownerLabel={ownerLabel}
          onUpdate={updateQuickTask}
          onEdit={setEditingTask}
          onAdd={() => setAddingTask(true)}
          filtered={filtersActive}
          onClearFilters={clearFilters}
        />
      )}

      {view === "workspace" && tasks && scope === "mine" && (
        <TaskWaitingStrip tasks={tasks.filter((task) => task.delegated && task.status !== "done")} onOwner={(owner) => { changeScope("waiting"); setOwnerFilter(owner); }} onAll={() => changeScope("waiting")} />
      )}

      {view === "list" && filtered && filtered.length > 0 && (
        <>
          {selectedIds.size > 0 && (
            <div className="sticky top-3 z-10 flex flex-wrap items-center gap-2 rounded-xl border bg-popover px-3 py-2 shadow-md">
              <span className="text-sm font-medium">{selectedIds.size} selected</span>
              <select
                value=""
                onChange={(event) => event.target.value && void applyBulk({ status: event.target.value })}
                disabled={bulkBusy}
                aria-label="Set status for selected"
                className={selectClass}
              >
                <option value="">Set status…</option>
                {STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
              </select>
              <form
                className="flex items-center gap-1.5"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (bulkOwner.trim()) void applyBulk({ owner: bulkOwner.trim() });
                }}
              >
                <Input value={bulkOwner} onChange={(event) => setBulkOwner(event.target.value)} placeholder="Reassign to…" className="h-8 w-36" disabled={bulkBusy} list="task-owners" />
                <datalist id="task-owners">{options.allOwners.map((owner) => <option key={owner} value={owner} />)}</datalist>
                <Button type="submit" size="sm" variant="outline" disabled={bulkBusy || !bulkOwner.trim()}>Apply</Button>
              </form>
              {jira?.connected && selectedUnsent > 0 && (
                <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void sendSelectedToJira()}>
                  <Send /> Send {selectedUnsent} to Jira
                </Button>
              )}
              <Button size="sm" variant="outline" className="text-destructive hover:text-destructive" disabled={bulkBusy} onClick={() => askDelete(selectedTasks)}>
                <Trash2 /> Delete
              </Button>
              <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setSelectedIds(new Set())} disabled={bulkBusy}>
                <X /> Clear
              </Button>
            </div>
          )}

          <div className="overflow-hidden rounded-xl border bg-card">
            <div className="hidden items-center gap-3 border-b bg-muted/40 px-4 py-2 text-xs font-medium text-muted-foreground md:flex">
              <Checkbox
                checked={allSelected}
                onCheckedChange={(checked) => setSelectedIds(checked ? new Set(filtered.map((task) => task.id)) : new Set())}
                aria-label="Select all"
              />
              <span className="flex-1">Task</span>
              <span className="w-28">Owner</span>
              <span className="w-28">Due</span>
              <span className="w-28">Status</span>
              <span className="w-20" />
            </div>
            {[...DUE_BUCKETS, { value: "done" as const, label: "Done" }].map((bucket) => {
              const group = filtered.filter((task) => (task.status === "done" ? "done" : dueBucket(task)) === bucket.value);
              if (!group.length) return null;
              return (
                <section key={bucket.value} aria-label={bucket.label}>
                  <h3 className={cn("flex items-center gap-2 border-b bg-muted/20 px-4 py-1.5 text-xs font-medium text-muted-foreground", bucket.value === "overdue" && "text-destructive")}>
                    {bucket.label}
                    <span className="tabular-nums">{group.length}</span>
                  </h3>
                  {group.map((task) => (
                    <TaskRow
                      key={task.id}
                      task={task}
                      ownerLabel={ownerLabel(task)}
                      selected={selectedIds.has(task.id)}
                      onSelect={(checked) =>
                        setSelectedIds((current) => {
                          const next = new Set(current);
                          if (checked) next.add(task.id);
                          else next.delete(task.id);
                          return next;
                        })
                      }
                      onOpen={() => setEditingTask(task)}
                      onStatus={(status) => void setStatus(task, status)}
                      onDelete={() => askDelete([task])}
                      jira={jira}
                      onJiraSent={(key, status) => patchTasks({ id: task.id, jira_issue_key: key, jira_status: status })}
                    />
                  ))}
                </section>
              );
            })}
          </div>
        </>
      )}

      {view === "board" && filtered && filtered.length > 0 && (
        <TaskBoard
          tasks={filtered}
          ownerLabel={ownerLabel}
          onMove={(task, status) => void setStatus(task, status)}
          onOpen={setEditingTask}
          onDelete={(task) => askDelete([task])}
        />
      )}

      {view !== "workspace" && inScope && inScope.length > 0 && (
        <details>
          <summary className="w-fit rounded-sm text-sm text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring">Follow-up tools</summary>
          <div className="mt-4 flex flex-col gap-4">
            {scope === "waiting" && <WaitingPanel tasks={inScope} ownerFilter={ownerFilter} onOwner={(owner) => setOwnerFilter((current) => current === owner ? "" : owner)} onRemind={(owner, list) => void copyReminder(owner, list)} />}
            {(scope === "mine" || scope === "all") && <NudgesPanel tasks={inScope} notDuplicates={notDuplicates} onOpen={setEditingTask} onDone={(task) => void setStatus(task, "done")} onSnooze={(task) => void snooze(task)} onDelete={(task) => askDelete([task])} onNotDuplicate={dismissDuplicate} />}
          </div>
        </details>
      )}

      {editingTask && (
        <TaskEditDialog
          task={editingTask as EditableTask}
          open={!!editingTask}
          onOpenChange={(open) => !open && setEditingTask(null)}
          onSave={(fields) => saveTaskEdits(editingTask, fields)}
          subtasks={tasks?.filter((task) => task.parent_task_id === editingTask.id) ?? []}
          onAddSubtask={(description) => addSubtask(editingTask.id, description)}
          onJiraChange={(fields) => patchTasks({ id: editingTask.id, ...fields })}
          onDelete={() => askDelete([editingTask])}
        />
      )}
      <TaskEditDialog task={null} open={addingTask} onOpenChange={setAddingTask} onSave={createTask} />
      <DeleteConfirmationDialog
        open={!!pendingDelete}
        onOpenChange={(open) => !open && !deleting && setPendingDelete(null)}
        title={pendingDelete && pendingDelete.ids.length > 1 ? `Delete ${pendingDelete.ids.length} tasks?` : "Delete this task?"}
        description={`${pendingDelete?.label ?? ""} ${pendingDelete && pendingDelete.ids.length > 1 ? "move" : "moves"} to the Recycle Bin in Settings and ${pendingDelete && pendingDelete.ids.length > 1 ? "leave" : "leaves"} Company Memory search. Meetings stay.`}
        confirmLabel="Move to Recycle Bin"
        busy={deleting}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

/** Who owes you what: each person's open tasks from your meetings, with
 * how many are late, and a reminder you can paste to them. */
function WaitingPanel({
  tasks,
  ownerFilter,
  onOwner,
  onRemind,
}: {
  tasks: TaskListItem[];
  ownerFilter: string;
  onOwner: (owner: string) => void;
  onRemind: (owner: string, list: TaskListItem[]) => void;
}) {
  const people = useMemo(() => {
    const byOwner = new Map<string, TaskListItem[]>();
    for (const task of tasks) {
      if (task.status === "done" || !task.owner) continue;
      byOwner.set(task.owner, [...(byOwner.get(task.owner) ?? []), task]);
    }
    return [...byOwner.entries()]
      .map(([owner, list]) => ({ owner, list: list.sort(compareByUrgency), overdue: list.filter((task) => dueBucket(task) === "overdue").length }))
      .sort((a, b) => b.overdue - a.overdue || b.list.length - a.list.length);
  }, [tasks]);
  if (!people.length) return null;

  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-3">
      <h2 className="flex items-center gap-1.5 text-sm font-medium">
        <Hourglass className="size-4 text-primary" /> Waiting on {people.length} {people.length === 1 ? "person" : "people"}
      </h2>
      <div className="flex flex-wrap gap-2">
        {people.map(({ owner, list, overdue }) => (
          <div
            key={owner}
            className={cn("flex items-center gap-2 rounded-lg border py-1 pr-1 pl-1.5 text-sm", ownerFilter === owner && "border-primary ring-2 ring-primary/20")}
          >
            <button type="button" onClick={() => onOwner(owner)} className="flex items-center gap-2" aria-pressed={ownerFilter === owner}>
              <span className="flex size-6 items-center justify-center rounded-full bg-muted text-[10px] font-medium">{initials(owner)}</span>
              <span>{owner}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{list.length} open</span>
              {overdue > 0 && <span className="text-xs font-medium text-destructive tabular-nums">{overdue} late</span>}
            </button>
            <Button variant="ghost" size="icon-sm" onClick={() => onRemind(owner, list)} aria-label={`Copy a reminder for ${owner}`} title="Copy a reminder">
              <Copy />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Housekeeping Wilco noticed: tasks nobody has touched in weeks, and
 * tasks that look like the same follow-up twice. */
function NudgesPanel({
  tasks,
  notDuplicates,
  onOpen,
  onDone,
  onSnooze,
  onDelete,
  onNotDuplicate,
}: {
  tasks: TaskListItem[];
  notDuplicates: Set<string>;
  onOpen: (task: TaskListItem) => void;
  onDone: (task: TaskListItem) => void;
  onSnooze: (task: TaskListItem) => void;
  onDelete: (task: TaskListItem) => void;
  onNotDuplicate: (a: TaskListItem, b: TaskListItem) => void;
}) {
  const [openPanel, setOpenPanel] = useState<"stale" | "duplicates" | null>(null);
  const stale = useMemo(
    () => tasks.filter((task) => isStale(task)).sort((a, b) => daysSince(b.updated_at) - daysSince(a.updated_at)),
    [tasks],
  );
  const duplicates = useMemo(
    () => possibleDuplicates(tasks, 10).filter(([a, b]) => !notDuplicates.has(pairKey(a, b))).slice(0, 5),
    [tasks, notDuplicates],
  );
  if (!stale.length && !duplicates.length) return null;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-dashed bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Sparkles className="size-4 text-primary" />
        {stale.length > 0 && (
          <button
            type="button"
            onClick={() => setOpenPanel(openPanel === "stale" ? null : "stale")}
            className={cn("rounded-md px-2 py-0.5 hover:bg-muted", openPanel === "stale" && "bg-muted font-medium")}
          >
            {stale.length} task{stale.length === 1 ? " hasn't" : "s haven't"} moved in {STALE_DAYS}+ days — still relevant?
          </button>
        )}
        {duplicates.length > 0 && (
          <button
            type="button"
            onClick={() => setOpenPanel(openPanel === "duplicates" ? null : "duplicates")}
            className={cn("rounded-md px-2 py-0.5 hover:bg-muted", openPanel === "duplicates" && "bg-muted font-medium")}
          >
            {duplicates.length} possible duplicate{duplicates.length === 1 ? "" : "s"}
          </button>
        )}
      </div>

      {openPanel === "stale" && (
        <div className="flex flex-col divide-y rounded-lg border bg-card">
          {stale.slice(0, 8).map((task) => (
            <div key={task.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <button type="button" onClick={() => onOpen(task)} className="min-w-0 flex-1 text-left">
                <span className="block truncate text-sm">{task.description}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  Untouched for {daysSince(task.updated_at)} days · {task.owner || "Unassigned"} · {task.meeting_title}
                </span>
              </button>
              <Button size="sm" variant="ghost" onClick={() => onDone(task)}><Check /> Done</Button>
              <Button size="sm" variant="ghost" onClick={() => onSnooze(task)} title="Move the due date a week out"><CalendarPlus /> +1 week</Button>
              <Button size="sm" variant="ghost" className="hover:text-destructive" onClick={() => onDelete(task)}><Trash2 /> Delete</Button>
            </div>
          ))}
          {stale.length > 8 && <p className="px-3 py-2 text-xs text-muted-foreground">And {stale.length - 8} more — sort the list by due date to find them.</p>}
        </div>
      )}

      {openPanel === "duplicates" && (
        <div className="flex flex-col divide-y rounded-lg border bg-card">
          {duplicates.map(([a, b]) => (
            <div key={pairKey(a, b)} className="flex flex-col gap-2 px-3 py-2">
              {[a, b].map((task) => (
                <div key={task.id} className="flex items-center gap-2">
                  <button type="button" onClick={() => onOpen(task)} className="min-w-0 flex-1 text-left">
                    <span className="block truncate text-sm">{task.description}</span>
                    <span className="block truncate text-xs text-muted-foreground">{task.owner || "Unassigned"} · {task.meeting_title}</span>
                  </button>
                  <Button size="sm" variant="ghost" className="hover:text-destructive" onClick={() => onDelete(task)}><Trash2 /> Delete this one</Button>
                </div>
              ))}
              <Button size="sm" variant="ghost" className="self-start" onClick={() => onNotDuplicate(a, b)}>
                <CopyCheck /> Not duplicates
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TaskRow({
  task,
  ownerLabel,
  selected,
  onSelect,
  onOpen,
  onStatus,
  onDelete,
  jira,
  onJiraSent,
}: {
  task: TaskListItem;
  ownerLabel: string;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onOpen: () => void;
  onStatus: (status: string) => void;
  onDelete: () => void;
  jira: ReturnType<typeof useJiraStatus>;
  onJiraSent: (key: string, status: string | null) => void;
}) {
  const overdue = dueBucket(task) === "overdue";
  const due = formatDue(task);
  return (
    <div className="group flex flex-col gap-2 border-b px-4 py-3 last:border-b-0 hover:bg-muted/30 md:flex-row md:items-center md:gap-3">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Checkbox className="mt-0.5" checked={selected} onCheckedChange={(checked) => onSelect(checked === true)} aria-label={`Select ${task.description}`} />
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onOpen} className={cn("text-left text-sm leading-snug hover:text-primary", task.status === "done" && "text-muted-foreground line-through")}>
            {task.parent_task_id && <span className="mr-1 text-muted-foreground">↳</span>}
            {task.description}
          </button>
          <details className="mt-1 text-xs text-muted-foreground">
            <summary className="w-fit rounded-sm focus-visible:ring-2 focus-visible:ring-ring">Details</summary>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            {task.priority && <span className={cn("rounded px-1.5 py-px font-medium", priorityTone(task.priority))}>{task.priority}</span>}
            {task.project && (
              task.project_id ? (
                <Link href={`/projects/${task.project_id}`} className="flex items-center gap-1 hover:text-foreground"><FolderKanban className="size-3" />{task.project}</Link>
              ) : (
                <span className="flex items-center gap-1"><FolderKanban className="size-3" />{task.project}</span>
              )
            )}
            {task.meeting_hidden ? (
              <span className="truncate" title="Sent to you from a meeting you weren't in: you have the task, not the meeting">{task.meeting_title}</span>
            ) : (
              <Link href={`/meetings/${task.meeting_id}`} className="truncate hover:text-foreground hover:underline">{task.meeting_title}</Link>
            )}
            {isStale(task) && <span className="text-warning" title={`No changes for ${daysSince(task.updated_at)} days`}>· quiet {daysSince(task.updated_at)}d</span>}
            <VerificationBadge verifiedAt={task.verified_at} />
            <JiraTaskButton taskId={task.id} issueKey={task.jira_issue_key} issueStatus={task.jira_status} issueError={task.jira_error} jira={jira} onSent={onJiraSent} />
          </div>
          </details>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-7 text-sm md:flex-nowrap md:pl-0">
        <span className="truncate text-muted-foreground md:w-28">{ownerLabel}</span>
        <span className={cn("flex items-center gap-1 truncate text-muted-foreground md:w-28", overdue && "font-medium text-destructive")}>
          {overdue && <AlertTriangle className="size-3 shrink-0" />}
          {due || "No date"}
        </span>
        <select
          value={task.status}
          onChange={(event) => onStatus(event.target.value)}
          aria-label="Status"
          className={cn("h-7 w-28 shrink-0 rounded-md border-0 px-2 text-xs font-medium", statusTone(task.status))}
        >
          {STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
        </select>
        <div className="ml-auto flex justify-end gap-0.5 md:ml-0 md:w-20">
          <Button variant="ghost" size="icon-sm" onClick={onOpen} aria-label="Edit task"><Pencil /></Button>
          <Button variant="ghost" size="icon-sm" className="hover:text-destructive" onClick={onDelete} aria-label="Delete task"><Trash2 /></Button>
        </div>
      </div>
    </div>
  );
}

function TaskBoard({
  tasks,
  ownerLabel,
  onMove,
  onOpen,
  onDelete,
}: {
  tasks: TaskListItem[];
  ownerLabel: (task: TaskListItem) => string;
  onMove: (task: TaskListItem, status: string) => void;
  onOpen: (task: TaskListItem) => void;
  onDelete: (task: TaskListItem) => void;
}) {
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [showAllDone, setShowAllDone] = useState(false);

  // A card dropped in another column re-renders there, so the original
  // element's dragend never fires and the card would stay faded. Clear the
  // drag state on any drop or drag end anywhere on the page.
  useEffect(() => {
    if (!draggingId) return;
    const reset = () => {
      setDraggingId(null);
      setDragOver(null);
    };
    window.addEventListener("drop", reset);
    window.addEventListener("dragend", reset);
    return () => {
      window.removeEventListener("drop", reset);
      window.removeEventListener("dragend", reset);
    };
  }, [draggingId]);

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {STATUSES.map((status) => {
        let column = tasks.filter((task) => task.status === status);
        const total = column.length;
        if (status === "done") {
          // Finished work piles up; the most recent is what you want to see.
          column = [...column].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
          if (!showAllDone) column = column.slice(0, DONE_SHOWN);
        }
        return (
          <div
            key={status}
            onDragOver={(event) => {
              event.preventDefault();
              setDragOver(status);
            }}
            onDragLeave={() => setDragOver((current) => (current === status ? null : current))}
            onDrop={(event) => {
              event.preventDefault();
              setDragOver(null);
              setDraggingId(null);
              const task = tasks.find((item) => item.id === event.dataTransfer.getData("text/plain"));
              if (task && task.status !== status) onMove(task, status);
            }}
            className={cn("flex min-h-64 flex-col gap-2 rounded-xl bg-muted/50 p-2 transition-colors", dragOver === status && "bg-primary/10 ring-2 ring-primary/30")}
          >
            <div className="flex items-center justify-between px-2 pt-1 pb-1">
              <h3 className="flex items-center gap-2 text-sm font-medium">
                <span className={cn("size-2 rounded-full", status === "done" ? "bg-success" : status === "in_progress" ? "bg-primary" : "bg-muted-foreground/50")} />
                {STATUS_LABELS[status]}
              </h3>
              <span className="text-xs text-muted-foreground tabular-nums">{total}</span>
            </div>
            {total === 0 && <p className="px-2 py-8 text-center text-xs text-muted-foreground">Drop a task here</p>}
            {column.map((task) => (
              <BoardCard
                key={task.id}
                task={task}
                ownerLabel={ownerLabel(task)}
                dragging={draggingId === task.id}
                onDragStart={() => setDraggingId(task.id)}
                onDragEnd={() => setDraggingId(null)}
                onOpen={() => onOpen(task)}
                onToggleDone={() => onMove(task, task.status === "done" ? "pending" : "done")}
                onDelete={() => onDelete(task)}
              />
            ))}
            {status === "done" && total > DONE_SHOWN && (
              <Button variant="ghost" size="sm" onClick={() => setShowAllDone(!showAllDone)}>
                {showAllDone ? "Show recent only" : `Show all ${total}`}
              </Button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function BoardCard({
  task,
  ownerLabel,
  dragging,
  onDragStart,
  onDragEnd,
  onOpen,
  onToggleDone,
  onDelete,
}: {
  task: TaskListItem;
  ownerLabel: string;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onOpen: () => void;
  onToggleDone: () => void;
  onDelete: () => void;
}) {
  const bucket = dueBucket(task);
  const due = formatDue(task);
  const done = task.status === "done";
  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", task.id);
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
        if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onOpen();
        }
      }}
      aria-label={task.description}
      className={cn(
        "group relative flex w-full cursor-pointer flex-col items-start gap-2 rounded-xl border bg-card p-3.5 text-left text-sm transition-colors hover:border-foreground/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        dragging && "opacity-40",
      )}
    >
      <div className="absolute top-1.5 right-1.5 flex gap-0.5 rounded-md bg-card opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 max-md:opacity-100">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={(event) => {
            event.stopPropagation();
            onToggleDone();
          }}
          aria-label={done ? "Reopen task" : "Mark done"}
          title={done ? "Reopen" : "Mark done"}
        >
          {done ? <RotateCcw /> : <Check />}
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="hover:text-destructive"
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          aria-label="Delete task"
          title="Delete"
        >
          <Trash2 />
        </Button>
      </div>
      <span className={cn("pr-14 leading-snug", done && "text-muted-foreground line-through")}>
        {task.parent_task_id && <span className="mr-1 text-muted-foreground">↳</span>}
        {task.description}
      </span>
      <span className="w-full truncate text-xs text-muted-foreground">
        {task.project ? `${task.project} · ` : ""}
        {task.meeting_title}
      </span>
      <span className="flex w-full flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {!done && priorityPill(task.priority) && (
          <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-px font-medium", priorityPill(task.priority))}>
            <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
            {task.priority}
          </span>
        )}
        <span className="flex items-center gap-1.5" title={ownerLabel}>
          <span className="flex size-5 items-center justify-center rounded-full bg-muted text-[10px] font-medium">{task.owner?.trim() ? initials(task.owner) : "?"}</span>
          {ownerLabel}
        </span>
        {isStale(task) && <span title={`No changes for ${daysSince(task.updated_at)} days`}>· quiet</span>}
        {due && (
          <span
            className={cn(
              "ml-auto flex items-center gap-1 rounded px-1.5 py-px",
              !done && bucket === "overdue" && "bg-destructive/10 font-medium text-destructive",
              !done && bucket === "today" && "bg-warning/15 font-medium text-foreground",
            )}
          >
            {!done && bucket === "overdue" && <AlertTriangle className="size-3" />}
            {due}
          </span>
        )}
      </span>
    </div>
  );
}
