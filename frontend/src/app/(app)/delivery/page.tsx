"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleAlert, Clock3, GitPullRequest, Radar, RefreshCw, Sparkles } from "lucide-react";
import { api, type DecisionListItem, type ProjectSummary, type TaskListItem } from "@/lib/api";
import "./delivery-radar.css";

type RadarFilter = "attention" | "all" | "completed";

function parseDueDate(value: string) {
  const localDate = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value;
  return new Date(localDate);
}

function isOverdue(task: TaskListItem) {
  if (task.status === "done" || !task.due_date) return false;
  const date = parseDueDate(task.due_date);
  return !Number.isNaN(date.getTime()) && date.getTime() < new Date(new Date().toDateString()).getTime();
}

function dueLabel(task: TaskListItem) {
  if (isOverdue(task)) return "Overdue";
  if (!task.due_date) return task.deadline || "No date";
  const date = parseDueDate(task.due_date);
  return Number.isNaN(date.getTime()) ? task.due_date : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function DeliveryRadarPage() {
  const [tasks, setTasks] = useState<TaskListItem[] | null>(null);
  const [decisions, setDecisions] = useState<DecisionListItem[] | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [filter, setFilter] = useState<RadarFilter>("attention");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [tasksResult, decisionsResult, projectsResult] = await Promise.allSettled([
      api.listTasks(), api.listDecisions(), api.listProjects(),
    ]);
    if (tasksResult.status === "fulfilled") setTasks(tasksResult.value);
    if (decisionsResult.status === "fulfilled") setDecisions(decisionsResult.value);
    if (projectsResult.status === "fulfilled") setProjects(projectsResult.value);
    if ([tasksResult, decisionsResult, projectsResult].some((result) => result.status === "rejected")) {
      setError("Some delivery signals couldn’t load. Try refreshing this view.");
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const openTasks = useMemo(() => (tasks ?? []).filter((task) => task.status !== "done"), [tasks]);
  const overdue = useMemo(() => openTasks.filter(isOverdue), [openTasks]);
  const attention = useMemo(() => openTasks.filter((task) => isOverdue(task) || task.priority?.toLowerCase() === "high"), [openTasks]);
  const visibleTasks = useMemo(() => {
    if (filter === "completed") return (tasks ?? []).filter((task) => task.status === "done").slice(0, 7);
    if (filter === "all") return openTasks.slice(0, 7);
    return attention.slice(0, 7);
  }, [attention, filter, openTasks, tasks]);
  const recentDecisions = useMemo(() => [...(decisions ?? [])].sort((a, b) => Date.parse(b.meeting_date) - Date.parse(a.meeting_date)).slice(0, 4), [decisions]);

  return (
    <div className="delivery-radar">
      <header className="delivery-hero">
        <div className="delivery-hero-copy">
          <span className="delivery-eyebrow"><Radar aria-hidden="true" /> Delivery radar</span>
          <h1>Keep the work moving after the call.</h1>
          <p>One view of follow-ups, decisions, and project activity from meetings you can access.</p>
          <div className="delivery-hero-actions">
            <Link href="/tasks" className="delivery-primary-link">Open task board <ArrowRight aria-hidden="true" /></Link>
            <Link href="/projects" className="delivery-text-link">Explore projects <ArrowRight aria-hidden="true" /></Link>
          </div>
        </div>
        <div className="delivery-graphic" aria-hidden="true">
          <div className="delivery-orbit delivery-orbit-one" />
          <div className="delivery-orbit delivery-orbit-two" />
          <div className="delivery-orbit delivery-orbit-three" />
          <div className="delivery-radar-sweep" />
          <span className="delivery-dot delivery-dot-one" />
          <span className="delivery-dot delivery-dot-two" />
          <span className="delivery-dot delivery-dot-three" />
          <span className="delivery-graphic-caption">Meeting signals → delivery clarity</span>
        </div>
      </header>

      {error && <div className="delivery-error" role="alert"><span>{error}</span><button type="button" onClick={() => void load()} disabled={loading}><RefreshCw aria-hidden="true" /> Retry</button></div>}

      <section className="delivery-metrics" aria-label="Delivery overview">
        <div><span>Open follow-ups</span><strong>{tasks === null ? "—" : openTasks.length}</strong><small>From meetings you can see</small></div>
        <div><span>Needs attention</span><strong>{tasks === null ? "—" : attention.length}</strong><small>High priority or overdue</small></div>
        <div><span>Overdue</span><strong>{tasks === null ? "—" : overdue.length}</strong><small>Due dates that have passed</small></div>
        <div><span>Tracked projects</span><strong>{projects === null ? "—" : projects.length}</strong><small>With meeting context</small></div>
      </section>

      <div className="delivery-grid">
        <section className="delivery-panel delivery-tasks" aria-labelledby="delivery-tasks-title">
          <div className="delivery-panel-head"><div><span className="delivery-panel-icon"><GitPullRequest aria-hidden="true" /></span><h2 id="delivery-tasks-title">Follow-ups</h2></div><Link href="/tasks">See all <ArrowRight aria-hidden="true" /></Link></div>
          <div className="delivery-filters" role="group" aria-label="Filter follow-ups">
            {([["attention", "Needs attention"], ["all", "All open"], ["completed", "Completed"]] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
          </div>
          {loading && tasks === null ? <p className="delivery-empty">Loading follow-ups…</p> : visibleTasks.length ? (
            <ul className="delivery-task-list">{visibleTasks.map((task) => <li key={task.id}>
              <span className="delivery-task-indicator" data-overdue={isOverdue(task)} aria-hidden="true" />
              <div><strong>{task.description}</strong><small>{task.owner || "Unassigned"}{task.project ? ` · ${task.project}` : ""}</small></div>
              <span className="delivery-due" data-overdue={isOverdue(task)}>{dueLabel(task)}</span>
              <Link href={task.meeting_hidden ? "/tasks" : `/meetings/${task.meeting_id}`} aria-label={`Open source for ${task.description}`}><ArrowRight aria-hidden="true" /></Link>
            </li>)}</ul>
          ) : <div className="delivery-empty"><Sparkles aria-hidden="true" /><p>{filter === "attention" ? "Nothing urgent needs attention." : filter === "completed" ? "Completed follow-ups will appear here." : "Open follow-ups from your meetings will appear here."}</p><Link href="/tasks">Open tasks</Link></div>}
        </section>

        <div className="delivery-side">
          <section className="delivery-panel" aria-labelledby="delivery-decisions-title">
            <div className="delivery-panel-head"><div><span className="delivery-panel-icon"><CircleAlert aria-hidden="true" /></span><h2 id="delivery-decisions-title">Recent decisions</h2></div><Link href="/decisions">See all <ArrowRight aria-hidden="true" /></Link></div>
            {loading && decisions === null ? <p className="delivery-empty">Loading decisions…</p> : recentDecisions.length ? <ul className="delivery-decision-list">{recentDecisions.map((decision) => <li key={decision.id}><Link href={`/meetings/${decision.meeting_id}`}><strong>{decision.decision}</strong><small>{decision.project || decision.meeting_title}</small><ArrowRight aria-hidden="true" /></Link></li>)}</ul> : <div className="delivery-empty"><p>Decisions from your meetings will appear here.</p><Link href="/meetings">Browse meetings</Link></div>}
          </section>
          <section className="delivery-panel" aria-labelledby="delivery-projects-title">
            <div className="delivery-panel-head"><div><span className="delivery-panel-icon"><Clock3 aria-hidden="true" /></span><h2 id="delivery-projects-title">Project activity</h2></div><Link href="/projects">See all <ArrowRight aria-hidden="true" /></Link></div>
            {loading && projects === null ? <p className="delivery-empty">Loading projects…</p> : projects?.length ? <ul className="delivery-project-list">{projects.slice(0, 4).map((project) => <li key={project.id}><Link href={`/projects/${project.id}`}><strong>{project.name}</strong><span>{project.task_count} tasks · {project.decision_count} decisions</span><ArrowRight aria-hidden="true" /></Link></li>)}</ul> : <div className="delivery-empty"><p>Group meetings by project to see activity here.</p><Link href="/projects">Create a project</Link></div>}
          </section>
        </div>
      </div>
    </div>
  );
}
