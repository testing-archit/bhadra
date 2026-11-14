"use client";

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { CalendarDays, Check, ChevronRight, Clock3, FolderKanban, Loader2, Pencil, RotateCcw, UserRound, Video } from "lucide-react";
import { ApiError, type TaskListItem } from "@/lib/api";
import { dueBucket, formatDue } from "@/lib/tasks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/empty-state";

export type TaskQuickUpdate = { status?: string; owner?: string; due_date?: string; clear_due_date?: boolean };
type Change = { task: TaskListItem; fields: TaskQuickUpdate; message: string };
type ChangeTask = (task: TaskListItem, fields: TaskQuickUpdate, previous: TaskQuickUpdate, message: string) => Promise<void>;

export function TaskWorkspace({ tasks, completedCount, showingCompleted, onToggleCompleted, owners, ownerLabel, onUpdate, onEdit, onAdd, filtered, onClearFilters }: {
  tasks: TaskListItem[];
  completedCount: number;
  showingCompleted: boolean;
  onToggleCompleted: () => void;
  owners: string[];
  ownerLabel: (task: TaskListItem) => string;
  onUpdate: (task: TaskListItem, fields: TaskQuickUpdate) => Promise<void>;
  onEdit: (task: TaskListItem) => void;
  onAdd: () => void;
  filtered: boolean;
  onClearFilters: () => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastChange, setLastChange] = useState<Change | null>(null);
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());
  const ordered = tasks;

  function choose(task: TaskListItem) {
    if (busy) return;
    setExpandedId((id) => id === task.id ? null : task.id);
    setError(null);
  }

  const change: ChangeTask = async (task, fields, previous, message) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const index = ordered.findIndex((item) => item.id === task.id);
    const next = ordered[index + 1] ?? ordered[index - 1];
    try {
      await onUpdate(task, fields);
      setLastChange({ task, fields: previous, message });
      setExpandedId(null);
      if (next) rowRefs.current.get(next.id)?.focus({ preventScroll: true });
    } catch (cause) {
      rowRefs.current.get(task.id)?.focus({ preventScroll: true });
      setError(cause instanceof ApiError ? cause.message : "That change wasn’t saved. Try again.");
    } finally {
      setBusy(false);
    }
  };

  async function undo() {
    if (!lastChange || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onUpdate(lastChange.task, lastChange.fields);
      setLastChange(null);
      requestAnimationFrame(() => rowRefs.current.get(lastChange.task.id)?.focus({ preventScroll: true }));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Couldn’t undo. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function complete(task: TaskListItem) {
    void change(task, { status: task.status === "done" ? "pending" : "done" }, { status: task.status }, task.status === "done" ? "Task reopened." : "Task completed.");
  }

  const inspectorProps = { owners, busy, onChange: change, onEdit };

  return (
    <section className="task-workspace flex flex-col gap-3" aria-label="Task workspace" aria-busy={busy}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium">{showingCompleted ? "Completed" : "Open tasks"} <span className="ml-1 text-muted-foreground tabular-nums">{tasks.length}</span></h2>
        <Button variant="ghost" size="sm" onClick={onToggleCompleted} disabled={busy}>
          {showingCompleted ? "Back to open tasks" : `Completed${completedCount ? ` (${completedCount})` : ""}`}
        </Button>
      </div>
      {tasks.length ? (
        <ul className="grid grid-cols-1 items-start gap-3 md:grid-cols-2">
          {ordered.map((task) => {
            const open = expandedId === task.id;
            return (
              <li key={task.id} className={cn("task-action-card flex min-w-0 flex-col gap-3 rounded-2xl border bg-card p-4 sm:p-5", open && "border-primary/40 ring-1 ring-primary/15")}>
                <div className="flex items-center justify-between gap-3">
                  <Button variant="ghost" size="icon-lg" disabled={busy} aria-label={`${task.status === "done" ? "Reopen" : "Complete"} ${task.description}`} onClick={() => complete(task)}>
                    <span className={cn("flex size-5 items-center justify-center rounded-full border border-muted-foreground/40", task.status === "done" && "border-primary bg-primary text-primary-foreground")}>
                      {task.status === "done" && <Check aria-hidden="true" className="size-3" />}
                    </span>
                  </Button>
                  <div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
                    <Badge className="max-w-full" variant={dueBucket(task) === "overdue" ? "destructive" : "secondary"}>
                      <CalendarDays aria-hidden="true" /><span className="truncate">{dueBucket(task) === "overdue" ? "Overdue · " : ""}{formatDue(task) ?? "No date"}</span>
                    </Badge>
                    {task.priority === "High" && <Badge variant="outline">High priority</Badge>}
                    {task.status === "in_progress" && <Badge variant="outline">In progress</Badge>}
                  </div>
                </div>
                <button
                  type="button"
                  className="rounded-sm text-left text-base leading-relaxed font-medium break-words outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  ref={(element) => { if (element) rowRefs.current.set(task.id, element); else rowRefs.current.delete(task.id); }}
                  aria-label={`Open task: ${task.description}`}
                  aria-expanded={open}
                  disabled={busy}
                  onClick={() => choose(task)}
                  onKeyDown={(event) => {
                    if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
                    event.preventDefault();
                    const index = ordered.findIndex((item) => item.id === task.id);
                    const next = ordered[index + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1)];
                    if (next && !busy) { setExpandedId(null); rowRefs.current.get(next.id)?.focus(); }
                  }}
                >
                  <span className={cn(task.status === "done" && "text-muted-foreground line-through")}>{task.description}</span>
                </button>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                    <FolderKanban className="size-3.5 shrink-0" aria-hidden="true" />
                    <span className="truncate">{task.project || (task.meeting_hidden ? "Shared task" : task.meeting_title || "Added manually")}</span>
                  </span>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="flex size-7 items-center justify-center rounded-full bg-accent text-xs font-medium text-accent-foreground" title={ownerLabel(task)} aria-label={ownerLabel(task)}>{(task.owner?.trim() || "?")[0].toUpperCase()}</span>
                    {ownerLabel(task) !== "You" && <span className="max-w-20 truncate text-xs text-muted-foreground">{ownerLabel(task).split(/\s+/)[0]}</span>}
                    <Button variant="ghost" size="icon-sm" aria-label={`Details for ${task.description}`} aria-expanded={open} onClick={() => choose(task)} disabled={busy}><ChevronRight className={cn(open && "rotate-90")} /></Button>
                  </div>
                </div>
                {open && <div className="border-t pt-4"><TaskInspector key={task.id} task={task} {...inspectorProps} /></div>}
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyState icon={Check} title={filtered ? "No tasks match" : showingCompleted ? "No completed tasks yet" : "You’re all caught up"} description={filtered ? "Clear your filters to see more tasks." : showingCompleted ? "Completed tasks will stay here." : "Add a task or check what you’re waiting on."} action={filtered ? <Button variant="outline" onClick={onClearFilters}>Clear filters</Button> : !showingCompleted ? <Button variant="outline" onClick={onAdd}>Add task</Button> : undefined} />
      )}
      {lastChange && (
        <div className="flex flex-wrap items-center gap-2 px-1 text-sm" role="status">
          <Check className="size-4 text-success" aria-hidden="true" /><span className="text-muted-foreground">{lastChange.message}</span>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void undo()}><RotateCcw data-icon="inline-start" /> Undo</Button>
        </div>
      )}
      {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    </section>
  );
}

function TaskInspector({ task, owners, busy, onChange, onEdit }: {
  task: TaskListItem;
  owners: string[];
  busy: boolean;
  onChange: ChangeTask;
  onEdit: (task: TaskListItem) => void;
}) {
  const [panel, setPanel] = useState<"snooze" | "assign" | null>(null);
  const panelId = useId();
  const done = task.status === "done";

  function snooze(days: number) {
    const date = new Date();
    date.setDate(date.getDate() + days);
    const value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    void onChange(task, { due_date: value }, task.due_date ? { due_date: task.due_date } : { clear_due_date: true }, `Due date moved to ${formatDue({ ...task, due_date: value })}.`);
  }

  return (
    <div className="flex flex-col gap-5" aria-label="Task actions">
      <div className="flex flex-col gap-3 text-sm">
        {task.meeting_hidden ? <p className="text-muted-foreground">Meeting details aren’t shared with you.</p> : task.meeting_id ? <Link className="flex items-start gap-3 text-muted-foreground underline-offset-4 hover:text-primary hover:underline" href={`/meetings/${task.meeting_id}`}><Video className="mt-0.5 size-4 shrink-0" aria-hidden="true" /><span className="min-w-0 break-words">{task.meeting_title}</span></Link> : <p className="text-muted-foreground">Added manually</p>}
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
        <Button className="col-span-2 lg:col-span-1" disabled={busy} onClick={() => void onChange(task, { status: done ? "pending" : "done" }, { status: task.status }, done ? "Task reopened." : "Task completed.")}>
          {busy ? <Loader2 data-icon="inline-start" className="animate-spin motion-reduce:animate-none" /> : <Check data-icon="inline-start" />}{done ? "Reopen" : "Done"}
        </Button>
        <Button variant="outline" disabled={busy} aria-expanded={panel === "snooze"} aria-controls={`${panelId}-snooze`} onClick={() => setPanel(panel === "snooze" ? null : "snooze")}><Clock3 data-icon="inline-start" />Snooze</Button>
        <Button variant="outline" disabled={busy} aria-expanded={panel === "assign"} aria-controls={`${panelId}-assign`} onClick={() => setPanel(panel === "assign" ? null : "assign")}><UserRound data-icon="inline-start" />Reassign</Button>
      </div>
      <Button variant="ghost" className="self-start" onClick={() => onEdit(task)} disabled={busy}><Pencil data-icon="inline-start" /> Edit task</Button>
      <div id={`${panelId}-snooze`} hidden={panel !== "snooze"} className="flex flex-col gap-2 [&[hidden]]:hidden">
        <p className="text-xs text-muted-foreground">Move the due date to</p>
        <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy} onClick={() => snooze(1)}>Tomorrow</Button><Button variant="secondary" disabled={busy} onClick={() => snooze(7)}>In a week</Button><Button variant="ghost" disabled={busy} onClick={() => onEdit(task)}>Choose date</Button></div>
      </div>
      <div id={`${panelId}-assign`} hidden={panel !== "assign"} className="flex flex-col gap-2 [&[hidden]]:hidden">
        <p className="text-xs text-muted-foreground">Assign to</p>
        <div className="flex flex-wrap gap-2">{owners.filter((owner) => owner.toLowerCase() !== task.owner?.toLowerCase()).slice(0, 8).map((owner) => <Button key={owner} variant="secondary" className="max-w-full" disabled={busy} onClick={() => void onChange(task, { owner }, { owner: task.owner ?? "" }, `Assigned to ${owner}.`)}><span className="truncate">{owner}</span></Button>)}<Button variant="ghost" disabled={busy} onClick={() => onEdit(task)}>Someone else</Button></div>
      </div>
    </div>
  );
}

export function TaskWaitingStrip({ tasks, onOwner, onAll }: { tasks: TaskListItem[]; onOwner: (owner: string) => void; onAll: () => void }) {
  if (!tasks.length) return null;
  const people = new Map<string, number>();
  for (const task of tasks) if (task.owner?.trim()) people.set(task.owner, (people.get(task.owner) ?? 0) + 1);
  return (
    <section className="flex flex-wrap items-center gap-3 rounded-2xl border bg-card px-4 py-3" aria-label="Waiting on teammates">
      <h2 className="mr-1 text-sm font-medium">Waiting on</h2>
      {[...people].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([owner, count]) => (
        <Button key={owner} variant="ghost" className="gap-2" onClick={() => onOwner(owner)} aria-label={`${owner}, ${count} open tasks`}>
          <span className="flex size-7 items-center justify-center rounded-full bg-accent text-xs text-accent-foreground">{owner.trim()[0].toUpperCase()}</span>
          <span>{owner.split(/\s+/)[0]}</span><span className="text-muted-foreground tabular-nums">{count}</span>
        </Button>
      ))}
      <Button variant="ghost" className="ml-auto" onClick={onAll}>View all {tasks.length}<ChevronRight data-icon="inline-end" /></Button>
    </section>
  );
}
