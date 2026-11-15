"use client";

import { useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { CalendarDays, Check, ChevronRight, Clock3, Loader2, Pencil, RotateCcw, UserRound, Video } from "lucide-react";
import { ApiError, type TaskListItem } from "@/lib/api";
import { dueBucket, formatDue, taskDueDate } from "@/lib/tasks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { Menu, MenuContent, MenuGroup, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/menu";

export type TaskQuickUpdate = { status?: string; owner?: string; due_date?: string; clear_due_date?: boolean };
type Change = { task: TaskListItem; fields: TaskQuickUpdate; message: string };
type ChangeTask = (task: TaskListItem, fields: TaskQuickUpdate, previous: TaskQuickUpdate, message: string) => Promise<void>;


function dateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
}
function buildWeek() {
  const first = new Date();
  first.setHours(0,0,0,0);
  first.setDate(first.getDate() + (first.getDay() === 0 ? 1 : 1-first.getDay()));
  return Array.from({length:7},(_,index)=> { const date = new Date(first); date.setDate(date.getDate()+index); return date; });
}

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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [week] = useState(buildWeek);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastChange, setLastChange] = useState<Change | null>(null);
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());
  const surface = useRef<HTMLUListElement>(null);
  const positionsBefore = useRef<Map<string, number> | null>(null);
  const visible = day && !showingCompleted ? tasks.filter(task => { const due=taskDueDate(task); return due && dateKey(due)===day; }) : tasks;
  const selected = visible.find(task=>task.id===selectedId) ?? visible[0];
  const dueCounts = new Map<string,number>();
  for (const task of tasks) { const due=taskDueDate(task); if(due) dueCounts.set(dateKey(due),(dueCounts.get(dateKey(due))??0)+1); }
  const mobileDates = week.filter(date=>dueCounts.has(dateKey(date))).slice(0,3).map(dateKey);

  useLayoutEffect(() => {
    const before=positionsBefore.current; positionsBefore.current=null;
    if(!before || matchMedia("(prefers-reduced-motion: reduce)").matches || !surface.current) return;
    // Batch reads, then animate only transforms. No scrolling or layout loops.
    const moves=Array.from(surface.current.querySelectorAll<HTMLElement>("[data-task-id]")).map(row=>({row,delta:(before.get(row.dataset.taskId!)??row.getBoundingClientRect().top)-row.getBoundingClientRect().top}));
    for(const {row,delta} of moves) {
      if(!delta) continue;
      row.style.willChange="transform";
      row.animate([{transform:`translateY(${delta}px)`},{transform:"translateY(0)"}],{duration:180,easing:"cubic-bezier(.2,.8,.2,1)"}).finished.catch(()=>{}).finally(()=>{row.style.willChange="";});
    }
  },[tasks]);

  function rememberPositions() {
    positionsBefore.current=new Map(Array.from(surface.current?.querySelectorAll<HTMLElement>("[data-task-id]")??[]).map(row=>[row.dataset.taskId!,row.getBoundingClientRect().top]));
  }
  function choose(task: TaskListItem) { if(!busy){setSelectedId(task.id);setError(null);} }
  const change: ChangeTask = async(task,fields,previous,message)=> {
    if(busy) return;
    setBusy(true);setError(null);rememberPositions();
    const index=visible.findIndex(item=>item.id===task.id);
    const next=visible[index+1]??visible[index-1];
    try {
      await onUpdate(task,fields);
      setLastChange({task,fields:previous,message});
      setSelectedId(next?.id??task.id);
      if(next) rowRefs.current.get(next.id)?.focus({preventScroll:true});
    } catch(cause) {
      positionsBefore.current=null;
      setSelectedId(task.id);
      setError(cause instanceof ApiError?cause.message:"That change wasn’t saved. Try again.");
    } finally {setBusy(false);}
  };
  async function undo() {
    if(!lastChange||busy)return;
    setBusy(true);setError(null);rememberPositions();
    try {
      await onUpdate(lastChange.task,lastChange.fields);
      setSelectedId(lastChange.task.id);setLastChange(null);
      requestAnimationFrame(()=>rowRefs.current.get(lastChange.task.id)?.focus({preventScroll:true}));
    } catch(cause) {positionsBefore.current=null;setError(cause instanceof ApiError?cause.message:"Couldn’t undo. Try again.");}
    finally {setBusy(false);}
  }
  function complete(task:TaskListItem){void change(task,{status:task.status==="done"?"pending":"done"},{status:task.status},task.status==="done"?"Task reopened.":"Task completed.");}
  function snooze(task:TaskListItem,days:number){const date=new Date();date.setDate(date.getDate()+days);const due=dateKey(date);void change(task,{due_date:due},task.due_date?{due_date:task.due_date}:{clear_due_date:true},`Due date moved to ${formatDue({...task,due_date:due})}.`);}

  return (
    <section className="task-workspace task-flow" aria-label="Task workspace" aria-busy={busy}>
      <div className="task-flow-heading">
        <h2>{showingCompleted?"Completed":"Next up"} <span>{tasks.length}</span></h2>
        <Button variant="ghost" size="sm" disabled={busy} onClick={()=>{setDay(null);onToggleCompleted();}}>{showingCompleted?"Back to open tasks":`Completed${completedCount?` (${completedCount})`:""}`}</Button>
      </div>
      {!showingCompleted && <nav className="task-day-strip" aria-label="Filter tasks by due date">
        <button type="button" aria-pressed={!day} className="task-day" disabled={busy} onClick={()=>setDay(null)}><span>View</span><strong>All</strong></button>
        {week.map(date=>{const key=dateKey(date),count=dueCounts.get(key)??0;return <button key={key} type="button" className="task-day" data-empty={!count} data-mobile-hidden={!mobileDates.includes(key)} aria-pressed={day===key} aria-label={`Due ${date.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"})}`} disabled={busy||!count} onClick={()=>setDay(day===key?null:key)}><span>{date.toLocaleDateString(undefined,{weekday:"short"})}</span><strong>{date.getDate()}</strong><i data-has-tasks={count>0} aria-hidden="true" /></button>;})}
      </nav>}
      <div className="task-flow-paper">
        {visible.length ? <ul ref={surface} className="task-flow-rows">
          {visible.map(task=><li key={task.id} className="task-flow-row" data-task-id={task.id} data-selected={selected?.id===task.id}>
            <Button variant="ghost" size="icon-lg" disabled={busy} aria-label={`${task.status==="done"?"Reopen":"Complete"} ${task.description}`} onClick={()=>complete(task)}><span className={cn("task-completion",task.status==="done"&&"is-complete")}>{task.status==="done"&&<Check aria-hidden="true" />}</span></Button>
            <button type="button" className="task-flow-title" ref={element=>{if(element)rowRefs.current.set(task.id,element);else rowRefs.current.delete(task.id);}} aria-label={`Open task: ${task.description}`} aria-pressed={selected?.id===task.id} disabled={busy} onClick={()=>choose(task)} onKeyDown={event=>{if(!["ArrowDown","ArrowUp"].includes(event.key))return;event.preventDefault();const i=visible.findIndex(item=>item.id===task.id),next=visible[i+(event.key==="ArrowDown"?1:-1)];if(next&&!busy){choose(next);rowRefs.current.get(next.id)?.focus();}}}>
              <span className={cn(task.status==="done"&&"line-through text-muted-foreground")}>{task.description}</span>
              <small>{formatDue(task)??"No due date"}{ownerLabel(task)!=="You"?` · ${ownerLabel(task)}`:""}</small>
            </button>
            {task.priority==="High"&&<span className="task-high-priority">High</span>}
            {task.status==="in_progress"&&<span className="task-in-progress">In progress</span>}
          </li>)}
        </ul> : <div className="task-flow-empty"><EmptyState icon={Check} title={day?"No tasks due on this day":filtered?"No tasks match":showingCompleted?"No completed tasks yet":"You’re all caught up"} description={filtered?"Clear your filters to see more tasks.":undefined} action={day?<Button variant="outline" onClick={()=>setDay(null)}>Show all dates</Button>:filtered?<Button variant="outline" onClick={onClearFilters}>Clear filters</Button>:!showingCompleted?<Button variant="outline" onClick={onAdd}>Add task</Button>:undefined}/></div>}
        <div className="task-action-dock" aria-label="Task actions">
          {selected ? <>
            <div className="task-dock-context" aria-live="polite">
              <Video aria-hidden="true" className="size-4 shrink-0" />
              {selected.meeting_hidden?<span>Shared task</span>:selected.meeting_id?<Link href={`/meetings/${selected.meeting_id}`}>{selected.meeting_title}</Link>:<span>Added manually</span>}
              <span className="task-dock-owner"><UserRound aria-hidden="true" className="size-3.5" />{ownerLabel(selected)}</span>
            </div>
            <div className="task-dock-buttons">
              <Button variant="brand" disabled={busy} onClick={()=>complete(selected)}>{busy?<Loader2 data-icon="inline-start" className="animate-spin motion-reduce:animate-none"/>:<Check data-icon="inline-start"/>}{selected.status==="done"?"Reopen":"Done"}</Button>
              <Menu><MenuTrigger render={<Button variant="outline" disabled={busy}/> }><Clock3 data-icon="inline-start"/>Snooze</MenuTrigger><MenuContent side="top"><MenuGroup><MenuLabel>Move the due date to</MenuLabel><MenuItem onClick={()=>snooze(selected,1)}>Tomorrow</MenuItem><MenuItem onClick={()=>snooze(selected,7)}>In a week</MenuItem><MenuSeparator/><MenuItem onClick={()=>onEdit(selected)}>Choose date</MenuItem></MenuGroup></MenuContent></Menu>
              <Menu><MenuTrigger render={<Button variant="outline" disabled={busy}/> }><UserRound data-icon="inline-start"/>Reassign</MenuTrigger><MenuContent side="top"><MenuGroup><MenuLabel>Assign to</MenuLabel>{owners.filter(owner=>owner.toLowerCase()!==selected.owner?.toLowerCase()).slice(0,8).map(owner=><MenuItem key={owner} onClick={()=>void change(selected,{owner},{owner:selected.owner??""},`Assigned to ${owner}.`)}><span className="max-w-60 truncate">{owner}</span></MenuItem>)}<MenuSeparator/><MenuItem onClick={()=>onEdit(selected)}>Someone else</MenuItem></MenuGroup></MenuContent></Menu>
              <Button variant="ghost" size="icon" aria-label="Edit task" disabled={busy} onClick={()=>onEdit(selected)}><Pencil/></Button>
            </div>
          </>:<span className="text-sm text-muted-foreground">Queue clear</span>}
        </div>
      </div>
      {lastChange&&<div className="task-change-notice" role="status"><Check className="size-4 text-success" aria-hidden="true"/><span>{lastChange.message}</span><Button variant="ghost" size="sm" disabled={busy} onClick={()=>void undo()}><RotateCcw data-icon="inline-start"/>Undo</Button></div>}
      {error&&<p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    </section>
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
