"use client";

import { useRef, useState, type PointerEvent } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, CalendarDays, Check, Clock3, Loader2, Pencil, RotateCcw, UserRound } from "lucide-react";
import { ApiError, type TaskListItem } from "@/lib/api";
import { dueBucket, formatDue } from "@/lib/tasks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";

export type FocusTaskUpdate = { status?: string; owner?: string; due_date?: string; clear_due_date?: boolean };
type Change = { task: TaskListItem; fields: FocusTaskUpdate; message: string };

/** Browsing never writes. Only the three explicit actions change a task. */
export function TaskFocusDeck({ tasks, owners, ownerLabel, onUpdate, onEdit, onAdd, filtered, onClearFilters }: {
  tasks: TaskListItem[];
  owners: string[];
  ownerLabel: (task: TaskListItem) => string;
  onUpdate: (task: TaskListItem, fields: FocusTaskUpdate) => Promise<void>;
  onEdit: (task: TaskListItem) => void;
  onAdd: () => void;
  filtered: boolean;
  onClearFilters: () => void;
}) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [deferredIds, setDeferredIds] = useState<string[]>([]);
  const [panel, setPanel] = useState<"snooze" | "assign" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastChange, setLastChange] = useState<Change | null>(null);
  const swipeStart = useRef<{ x: number; y: number; pointerId: number } | null>(null);
  // Snoozing sends a task to the back of this session's queue without hiding it.
  const queue = [...tasks].sort((a, b) => Number(deferredIds.includes(a.id)) - Number(deferredIds.includes(b.id)));
  const index = Math.max(0, queue.findIndex((task) => task.id === activeId));
  const task = queue[index];

  function browse(next: number) {
    if (busy || next < 0 || next >= queue.length) return;
    setActiveId(queue[next].id);
    setPanel(null);
    setError(null);
  }

  async function change(current: TaskListItem, fields: FocusTaskUpdate, previous: FocusTaskUpdate, message: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    const next = queue[index + 1] ?? queue[index - 1];
    try {
      await onUpdate(current, fields);
      setLastChange({ task: current, fields: previous, message });
      if (fields.due_date) setDeferredIds((ids) => [...ids.filter((id) => id !== current.id), current.id]);
      setActiveId(next?.id ?? null);
      setPanel(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That change wasn’t saved. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!lastChange || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onUpdate(lastChange.task, lastChange.fields);
      setActiveId(lastChange.task.id);
      setDeferredIds((ids) => ids.filter((id) => id !== lastChange.task.id));
      setPanel(null);
      setLastChange(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Couldn’t undo. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function snooze(days: number) {
    if (!task) return;
    const date = new Date();
    date.setDate(date.getDate() + days);
    const value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    void change(task, { due_date: value }, task.due_date ? { due_date: task.due_date } : { clear_due_date: true }, `Due date moved to ${formatDue({ ...task, due_date: value })}.`);
  }

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== "touch" || busy || (event.target as HTMLElement).closest("button, a, input, summary, select")) return;
    swipeStart.current = { x: event.clientX, y: event.clientY, pointerId: event.pointerId };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function pointerUp(event: PointerEvent<HTMLDivElement>) {
    const start = swipeStart.current;
    swipeStart.current = null;
    if (!start || start.pointerId !== event.pointerId) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (Math.abs(dx) >= 65 && Math.abs(dx) > Math.abs(dy) * 1.5) browse(index + (dx < 0 ? 1 : -1));
  }

  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-4" aria-label="Task focus deck" aria-busy={busy}>
      {task ? (
        <>
          <Card
            className="task-focus-surface touch-pan-y"
            onPointerDown={pointerDown}
            onPointerUp={pointerUp}
            onPointerCancel={() => { swipeStart.current = null; }}
          >
            <CardHeader>
              <CardTitle className="sr-only">Current task</CardTitle>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={dueBucket(task) === "overdue" ? "destructive" : "secondary"}>
                    <CalendarDays aria-hidden="true" /> {formatDue(task) ?? "No due date"}
                  </Badge>
                  {task.priority === "High" && <Badge variant="outline">High priority</Badge>}
                </div>
                <span className="text-sm text-muted-foreground">{ownerLabel(task)}</span>
              </div>
            </CardHeader>
            <CardContent>
              <div key={task.id} className="task-focus-arrive flex min-h-40 flex-col justify-center py-6" aria-live="polite" aria-atomic="true">
                <h2 className="text-2xl leading-snug font-medium tracking-tight text-balance break-words sm:text-3xl">{task.description}</h2>
              </div>
              <div className="grid grid-cols-3 gap-2 sm:flex sm:gap-3">
                <Button size="lg" disabled={busy} onClick={() => void change(task, { status: "done" }, { status: task.status }, "Task completed.")}>
                  {busy ? <Loader2 data-icon="inline-start" className="animate-spin motion-reduce:animate-none" /> : <Check data-icon="inline-start" />} Done
                </Button>
                <Button size="lg" variant="outline" disabled={busy} aria-expanded={panel === "snooze"} aria-controls="focus-snooze" onClick={() => setPanel(panel === "snooze" ? null : "snooze")}>
                  <Clock3 data-icon="inline-start" /> Snooze
                </Button>
                <Button size="lg" variant="outline" disabled={busy} aria-expanded={panel === "assign"} aria-controls="focus-assign" onClick={() => setPanel(panel === "assign" ? null : "assign")}>
                  <UserRound data-icon="inline-start" /> Reassign
                </Button>
              </div>
              {(
                <div hidden={panel !== "snooze"} id="focus-snooze" className="mt-5 flex flex-col gap-2 [&[hidden]]:hidden">
                  <p className="text-sm text-muted-foreground">Move the due date to</p>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" size="lg" disabled={busy} onClick={() => snooze(1)}>Tomorrow</Button>
                    <Button variant="secondary" size="lg" disabled={busy} onClick={() => snooze(7)}>In a week</Button>
                    <Button variant="ghost" size="lg" disabled={busy} onClick={() => onEdit(task)}>Choose date</Button>
                  </div>
                </div>
              )}
              {(
                <div hidden={panel !== "assign"} id="focus-assign" className="mt-5 flex flex-col gap-2 [&[hidden]]:hidden">
                  <p className="text-sm text-muted-foreground">Assign to</p>
                  <div className="flex flex-wrap gap-2">
                    {owners.filter((owner) => owner.toLowerCase() !== task.owner?.toLowerCase()).map((owner) => (
                      <Button key={owner} variant="secondary" size="lg" disabled={busy} onClick={() => void change(task, { owner }, { owner: task.owner ?? "" }, `Assigned to ${owner}.`)}>{owner}</Button>
                    ))}
                    <Button variant="ghost" size="lg" disabled={busy} onClick={() => onEdit(task)}>Someone else</Button>
                  </div>
                </div>
              )}
            </CardContent>
            <CardFooter className="flex-col items-stretch gap-3">
              <details key={task.id}>
                <summary className="w-fit rounded-sm text-sm text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">Meeting context</summary>
                <div className="mt-4 flex flex-col items-start gap-3 text-sm">
                  {task.meeting_hidden ? <p className="text-muted-foreground">Meeting details aren’t shared with you.</p> : task.meeting_id ? <Link className="text-primary underline-offset-4 hover:underline" href={`/meetings/${task.meeting_id}`}>{task.meeting_title}</Link> : <p className="text-muted-foreground">Added manually</p>}
                  {task.project && <p className="text-muted-foreground">Project: {task.project}</p>}
                  {task.status === "in_progress" && <Badge variant="outline">In progress</Badge>}
                  <Button variant="outline" onClick={() => onEdit(task)} disabled={busy}><Pencil data-icon="inline-start" /> Edit task</Button>
                </div>
              </details>
            </CardFooter>
          </Card>
          <nav className="flex items-center justify-center gap-5" aria-label="Browse tasks">
            <Button variant="outline" size="icon-lg" disabled={busy || index === 0} onClick={() => browse(index - 1)} aria-label="Previous task"><ArrowLeft /></Button>
            <span className="min-w-20 text-center text-sm tabular-nums text-muted-foreground" aria-live="polite">{index + 1} of {queue.length}</span>
            <Button variant="outline" size="icon-lg" disabled={busy || index === queue.length - 1} onClick={() => browse(index + 1)} aria-label="Next task"><ArrowRight /></Button>
          </nav>
        </>
      ) : (
        <EmptyState icon={Check} title={filtered ? "No tasks match" : "You’re all caught up"} description={filtered ? "Clear your filters to see more tasks." : "New tasks will appear here after your meetings."} action={filtered ? <Button variant="outline" onClick={onClearFilters}>Clear filters</Button> : <Button variant="outline" onClick={onAdd}>Add task</Button>} />
      )}
      <div className="flex min-h-11 flex-wrap items-center justify-center gap-2 text-sm" role="status">
        {lastChange && <><span className="text-muted-foreground">{lastChange.message}</span><Button variant="ghost" disabled={busy} onClick={() => void undo()}><RotateCcw data-icon="inline-start" /> Undo</Button></>}
      </div>
      {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    </section>
  );
}
