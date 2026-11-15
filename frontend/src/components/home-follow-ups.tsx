"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, ChevronRight, RotateCcw } from "lucide-react";
import {
  api,
  ApiError,
  type TaskListItem,
  type TaskUpdateResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { compareByUrgency, dueBucket, formatDue, isMyTask } from "@/lib/tasks";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function HomeFollowUps({
  tasks,
  loading,
  onUpdated,
  onRetry,
}: {
  tasks: TaskListItem[] | null;
  loading: boolean;
  onUpdated: (updated: TaskUpdateResponse) => void;
  onRetry: () => void;
}) {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastDone, setLastDone] = useState<TaskListItem | null>(null);
  const undoRef = useRef<HTMLButtonElement>(null);
  const completionRefs = useRef(new Map<string, HTMLButtonElement>());
  const restoreFocus = useRef<string | null>(null);
  useEffect(() => {
    if (lastDone) undoRef.current?.focus({ preventScroll: true });
    else if (restoreFocus.current) {
      completionRefs.current
        .get(restoreFocus.current)
        ?.focus({ preventScroll: true });
      restoreFocus.current = null;
    }
  }, [lastDone]);
  const mine = (tasks ?? []).filter((task) => isMyTask(task, user));
  const open = mine
    .filter((task) => task.status !== "done")
    .sort(compareByUrgency);
  const completed = mine.filter((task) => task.status === "done").length;
  const waitingRows=(tasks??[]).filter(task=>!isMyTask(task,user)&&task.owner?.trim()&&task.status!=="done");
  const waitingNames=[...new Set(waitingRows.map(task=>task.owner!))].slice(0,3);
  const shown=mine.filter(task=>task.status!=="done"||task.id===lastDone?.id).sort(compareByUrgency).slice(0,4);
  const waiting = (tasks ?? []).filter(
    (task) => task.delegated && task.status !== "done",
  ).length;

  async function complete(task: TaskListItem) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateTaskStatus(task.id, "done");
      onUpdated(updated);
      setLastDone(task);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "That task wasn’t saved. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function undo() {
    if (!lastDone || busy) return;
    setBusy(true);
    setError(null);
    try {
      onUpdated(await api.updateTaskStatus(lastDone.id, lastDone.status));
      restoreFocus.current = lastDone.id;
      setLastDone(null);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Couldn’t undo. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="work-sheet home-follow-ups"
      aria-labelledby="home-follow-ups-heading"
      aria-busy={busy || loading}
    >
      <header className="home-panel-heading">
        <h2 id="home-follow-ups-heading">Yours to move.</h2>
        <div className="waiting-initials" aria-label="Waiting on teammates">{waitingNames.map(name=><Link key={name} href="/tasks?scope=waiting" title={name} aria-label={`Waiting on ${name}`}>{name.split(/\s+/).map(part=>part[0]).join("").slice(0,2)}</Link>)}</div>
        <Link href="/tasks">
          All
          <ChevronRight aria-hidden="true" />
        </Link>
      </header>
      {loading && tasks === null ? (
        <Skeleton className="h-56 rounded-xl" />
      ) : tasks === null ? (
        <div className="home-small-empty" role="alert">
          <p>Follow-ups couldn’t load.</p>
          <Button variant="outline" onClick={onRetry}>
            Try again
          </Button>
        </div>
      ) : (
        <>
          {shown.length ? (
            <ul className="home-follow-up-list">
              {shown.map((task) => (
                <li key={task.id} data-complete={task.status==="done"}>
                  <Button
                    ref={(node) => {
                      if (node) completionRefs.current.set(task.id, node);
                      else completionRefs.current.delete(task.id);
                    }}
                    variant="ghost"
                    size="icon-lg"
                    disabled={busy||task.status==="done"}
                    onClick={() => void complete(task)}
                    aria-label={`${task.status==="done"?"Completed":"Complete"} ${task.description}`}
                    aria-pressed={task.status==="done"}
                  >
                    <span className={`task-completion ${task.status==="done"?"is-complete":""}`}>
                      <Check aria-hidden="true" />
                    </span>
                  </Button>
                  <Link
                    href={`/tasks?task=${encodeURIComponent(task.id)}`}
                    className="home-task-link"
                  >
                    <strong>{task.description}</strong>
                    <span>
                      {task.meeting_hidden ? "Shared task" : task.meeting_title}
                    </span>
                  </Link>
                  <span
                    className="home-task-due"
                    data-overdue={dueBucket(task) === "overdue"}
                  >
                    {formatDue(task) ?? "No date"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="home-small-empty">
              <Check aria-hidden="true" />
              <p>
                {mine.length
                  ? "Your follow-ups are complete."
                  : "Your meeting follow-ups will appear here."}
              </p>
              <Link href="/tasks?new=1">Add a follow-up</Link>
            </div>
          )}
          {open.length > 4 && (
            <Link href="/tasks" className="home-more-tasks">
              {open.length - 4} more
              <ChevronRight aria-hidden="true" />
            </Link>
          )}
          {lastDone && (
            <div className="home-task-feedback" role="status">
              <Check aria-hidden="true" />
              <span>Done.</span>
              <Button
                ref={undoRef}
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void undo()}
              >
                <RotateCcw data-icon="inline-start" aria-hidden="true" />
                Undo
              </Button>
            </div>
          )}

        </>
      )}
      {error && (
        <p className="home-action-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
