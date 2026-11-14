import type { Me, TaskListItem } from "./api";
import { isTaskOverdue, parseRelativeDeadline } from "./deadline";

import { STATUS_LABELS } from "./labels";
/** Whether a task's free-text owner refers to this user. Owners come from
 * transcripts, so "Archit", "Archit Jain" and the email all count. */
export function isMine(task: Pick<TaskListItem, "owner">, user: Pick<Me, "name" | "email"> | null): boolean {
  if (!task.owner || !user) return false;
  const owner = task.owner.trim().toLowerCase();
  const email = user.email.toLowerCase();
  const candidates = new Set([email, email.split("@")[0]]);
  if (user.name) {
    const name = user.name.trim().toLowerCase();
    candidates.add(name);
    candidates.add(name.split(/\s+/)[0]);
  }
  return candidates.has(owner);
}

/** Absolute due date when one can be worked out, else null. */
export function taskDueDate(task: Pick<TaskListItem, "due_date" | "deadline" | "meeting_date">): Date | null {
  if (task.due_date) {
    // A bare YYYY-MM-DD is a calendar day here, not UTC midnight.
    const [year, month, day] = task.due_date.split("-").map(Number);
    const parsed = year && month && day ? new Date(year, month - 1, day) : new Date(task.due_date);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return task.deadline ? parseRelativeDeadline(task.deadline, task.meeting_date) : null;
}

/** Overdue first, then soonest due, then undated — newest meetings first. */
export function compareByUrgency(a: TaskListItem, b: TaskListItem): number {
  const overdueA = isTaskOverdue(a.deadline, a.meeting_date, a.status, a.due_date);
  const overdueB = isTaskOverdue(b.deadline, b.meeting_date, b.status, b.due_date);
  if (overdueA !== overdueB) return overdueA ? -1 : 1;
  const dueA = taskDueDate(a)?.getTime() ?? Infinity;
  const dueB = taskDueDate(b)?.getTime() ?? Infinity;
  if (dueA !== dueB) return dueA - dueB;
  return new Date(b.meeting_date).getTime() - new Date(a.meeting_date).getTime();
}

export function formatDue(task: Pick<TaskListItem, "due_date" | "deadline" | "meeting_date">): string | null {
  const due = taskDueDate(task);
  if (due) return due.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  return task.deadline || null;
}

function csvCell(value: string | null | undefined): string {
  // Excel and Sheets run a cell starting with = + - @ as a formula.
  const raw = value ?? "";
  const text = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function tasksToCsv(tasks: TaskListItem[]): string {
  const header = ["Task", "Owner", "Status", "Priority", "Due", "Project", "Meeting", "Meeting date", "Jira"];
  const rows = tasks.map((task) => [
    task.description,
    task.owner,
    STATUS_LABELS[task.status] ?? task.status,
    task.priority,
    formatDue(task),
    task.project,
    task.meeting_title,
    new Date(task.meeting_date).toLocaleDateString(),
    task.jira_issue_key ?? "",
  ]);
  return [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
}

// --- intelligence: what to do next, what's gone stale, what's duplicated ---

const DAY = 24 * 60 * 60 * 1000;
/** Not touched for this long while still open: worth asking if it still matters. */
export const STALE_DAYS = 14;

function startOfToday(now = new Date()): Date {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  return today;
}

/** The task's owner relationship to the viewer, server-computed when available. */
export function isMyTask(task: TaskListItem, user: Pick<Me, "name" | "email"> | null): boolean {
  return task.mine ?? isMine(task, user);
}

export type DueBucket = "overdue" | "today" | "week" | "later" | "none";
export const DUE_BUCKETS: { value: DueBucket; label: string }[] = [
  { value: "overdue", label: "Overdue" },
  { value: "today", label: "Due today" },
  { value: "week", label: "Next 7 days" },
  { value: "later", label: "Later" },
  { value: "none", label: "No due date" },
];

export function dueBucket(task: TaskListItem, now = new Date()): DueBucket {
  const due = taskDueDate(task);
  if (!due) return "none";
  const today = startOfToday(now).getTime();
  const day = startOfToday(due).getTime();
  if (day < today) return task.status === "done" ? "later" : "overdue";
  if (day === today) return "today";
  if (day <= today + 7 * DAY) return "week";
  return "later";
}

export function daysSince(iso: string | null | undefined, now = new Date()): number {
  if (!iso) return 0;
  const then = new Date(iso).getTime();
  return Number.isNaN(then) ? 0 : Math.floor((now.getTime() - then) / DAY);
}

export function isStale(task: TaskListItem, now = new Date()): boolean {
  return task.status !== "done" && daysSince(task.updated_at, now) >= STALE_DAYS && dueBucket(task, now) !== "today";
}

/** How much a task wants doing now, and why in plain words. Overdue and
 * due-soon work first, weighted by priority; in-progress work gets a nudge
 * to finish; old untouched work drifts down unless it is overdue. */
export function urgency(task: TaskListItem, now = new Date()): { score: number; reasons: string[] } {
  const reasons: string[] = [];
  let score = 0;
  const due = taskDueDate(task);
  const bucket = dueBucket(task, now);
  if (bucket === "overdue" && due) {
    const late = Math.max(1, Math.round((startOfToday(now).getTime() - startOfToday(due).getTime()) / DAY));
    score += 100 + Math.min(late, 30) * 2;
    reasons.push(`Overdue by ${late} day${late === 1 ? "" : "s"}`);
  } else if (bucket === "today") {
    score += 80;
    reasons.push("Due today");
  } else if (bucket === "week" && due) {
    const left = Math.round((startOfToday(due).getTime() - startOfToday(now).getTime()) / DAY);
    score += left <= 1 ? 65 : 45 - left * 2;
    reasons.push(left <= 1 ? "Due tomorrow" : `Due in ${left} days`);
  } else if (bucket === "later") {
    score += 10;
  } else {
    score += 5;
  }
  if (task.priority === "High") {
    score += 25;
    reasons.push("High priority");
  } else if (task.priority === "Medium") {
    score += 10;
  }
  if (task.status === "in_progress") {
    score += 8;
    reasons.push("Already started");
  }
  if (bucket !== "overdue" && isStale(task, now)) score -= 5;
  return { score, reasons };
}

/** The few open tasks worth doing next, most urgent first. */
export function upNext(tasks: TaskListItem[], limit = 3, now = new Date()): { task: TaskListItem; reasons: string[] }[] {
  return tasks
    .filter((task) => task.status !== "done")
    .map((task) => ({ task, ...urgency(task, now) }))
    .sort((a, b) => b.score - a.score || compareByUrgency(a.task, b.task))
    .slice(0, limit)
    .map(({ task, reasons }) => ({ task, reasons: reasons.length ? reasons : ["Oldest open task"] }));
}

const STOPWORDS = new Set([
  "the", "and", "for", "with", "from", "into", "onto", "about", "this", "that", "to", "of", "on", "in", "a", "an",
  "by", "at", "be", "is", "it", "up", "out", "all", "any", "our", "their", "his", "her", "will", "should",
]);

function words(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((word) => word.length > 2 && !STOPWORDS.has(word)),
  );
}

/** Open tasks that say nearly the same thing (often the same follow-up
 * pulled from two meetings in a series). Word overlap, no AI call. */
export function possibleDuplicates(tasks: TaskListItem[], limit = 5): [TaskListItem, TaskListItem][] {
  const open = tasks.filter((task) => task.status !== "done").map((task) => ({ task, words: words(task.description) }));
  const pairs: { pair: [TaskListItem, TaskListItem]; overlap: number }[] = [];
  for (let i = 0; i < open.length; i++) {
    for (let j = i + 1; j < open.length; j++) {
      const a = open[i];
      const b = open[j];
      if (a.words.size < 2 || b.words.size < 2) continue;
      if (a.task.parent_task_id === b.task.id || b.task.parent_task_id === a.task.id) continue;
      let shared = 0;
      for (const word of a.words) if (b.words.has(word)) shared++;
      const overlap = shared / (a.words.size + b.words.size - shared);
      if (overlap >= 0.6) pairs.push({ pair: [a.task, b.task], overlap });
    }
  }
  return pairs.sort((x, y) => y.overlap - x.overlap).slice(0, limit).map(({ pair }) => pair);
}

/** Due date a week later than now or than the current one, whichever is later. */
export function snoozedDueDate(task: TaskListItem, days = 7, now = new Date()): string {
  const due = taskDueDate(task);
  const base = due && due.getTime() > startOfToday(now).getTime() ? due : startOfToday(now);
  const next = new Date(base.getTime() + days * DAY);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}`;
}

/** A short plain-text reminder of what someone still owes you. */
export function reminderText(owner: string, tasks: TaskListItem[]): string {
  const lines = tasks.map((task) => {
    const due = formatDue(task);
    return `• ${task.description}${due ? ` (due ${due})` : ""} — from “${task.meeting_title}”`;
  });
  return `Hi ${owner.split(" ")[0]}, a quick check on these follow-ups:\n${lines.join("\n")}\nThanks!`;
}
