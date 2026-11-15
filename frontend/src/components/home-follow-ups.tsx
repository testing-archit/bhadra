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
      className="home-work-panel"
      aria-labelledby="home-follow-ups-heading"
      aria-busy={busy || loading}
    >
      <header className="home-panel-heading">
        <h2 id="home-follow-ups-heading">Move a follow-up forward</h2>
        <Link href="/tasks">
          View all
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
          {mine.length > 0 && (
            <div className="home-task-progress">
              <div>
                <span>
                  {completed} of {mine.length} complete
                </span>
                <span>{open.length} open</span>
              </div>
              <span className="home-progress-track" aria-hidden="true">
                <span style={{ width: `${(completed / mine.length) * 100}%` }} />
              </span>
              <progress
                className="sr-only"
                value={completed}
                max={mine.length}
                aria-label="Completed follow-ups you own"
                aria-valuetext={`${completed} of ${mine.length} complete`}
              />
              <small>Across the follow-ups you own</small>
            </div>
          )}
          {open.length ? (
            <ul className="home-follow-up-list">
              {open.slice(0, 4).map((task) => (
                <li key={task.id}>
                  <Button
                    ref={(node) => {
                      if (node) completionRefs.current.set(task.id, node);
                      else completionRefs.current.delete(task.id);
                    }}
                    variant="ghost"
                    size="icon-lg"
                    disabled={busy}
                    onClick={() => void complete(task)}
                    aria-label={`Complete ${task.description}`}
                  >
                    <span className="task-completion">
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
              See {open.length - 4} more follow-ups
              <ChevronRight aria-hidden="true" />
            </Link>
          )}
          {lastDone && (
            <div className="home-task-feedback" role="status">
              <Check aria-hidden="true" />
              <span>Follow-up completed.</span>
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
          {waiting > 0 && (
            <Link className="home-waiting-link" href="/tasks?scope=waiting">
              Waiting on others <span>{waiting} open</span>
              <ChevronRight aria-hidden="true" />
            </Link>
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
