"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, ProjectDetail, ApiError } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";
import { ProjectNameEditor } from "@/components/project-name-editor";
import {
  ArrowLeft,
  FolderKanban,
  ListChecks,
  Scale,
  ShieldAlert,
  AlertTriangle,
  CalendarDays,
  Trash2,
} from "lucide-react";

import { STATUS_LABELS } from "@/lib/labels";
import "../../../signal-work.css";
export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    api
      .getProject(id)
      .then(setProject)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load project"));
  }, [id]);

  async function deleteProject() {
    if (!project) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProject(project.id);
      router.push("/projects");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Project could not be deleted");
      setDeleting(false);
    }
  }

  if (error) return <div className="signal-work"><p role="alert" className="text-sm text-destructive">{error}</p><Link className="signal-work-back mt-3 inline-flex items-center gap-1 text-sm" href="/projects"><ArrowLeft className="size-4" /> Back to projects</Link></div>;

  if (!project) {
    return (
      <div className="signal-work flex flex-col gap-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="signal-work flex flex-col gap-6">
      <div className="signal-work-intro flex items-start justify-between gap-4">
        <div>
        <Link
          href="/projects"
          className="signal-work-back flex items-center gap-1 text-sm hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to projects
        </Link>
        <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <FolderKanban className="h-5 w-5 shrink-0 text-primary" />
          <ProjectNameEditor
            projectId={project.id}
            name={project.name}
            onRenamed={(name) => setProject((current) => (current ? { ...current, name } : current))}
          />
        </h1>
        {project.department && (
          <Badge variant="secondary" className="mt-2">
            {project.department}
          </Badge>
        )}
        </div>
        <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => setDeleteOpen(true)}>
          <Trash2 className="h-4 w-4" /> Delete project
        </Button>
      </div>

      <div className="signal-work-stat-grid" aria-label="Project activity">
        <div className="signal-work-stat"><strong>{project.meetings.length}</strong><span>Meetings</span></div>
        <div className="signal-work-stat"><strong>{project.tasks.length}</strong><span>Tasks</span></div>
        <div className="signal-work-stat"><strong>{project.decisions.length}</strong><span>Decisions</span></div>
        <div className="signal-work-stat"><strong>{project.risks.length}</strong><span>Risks</span></div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarDays className="h-4 w-4 text-primary" />
            Meetings ({project.meetings.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {project.meetings.length === 0 && <p className="text-sm text-muted-foreground">No meetings assigned to this project yet.</p>}
          {project.meetings.map((meeting, index) => (
            <div key={meeting.id}>
              {index > 0 && <Separator className="mb-3" />}
              <Link href={`/meetings/${meeting.id}`} className="block hover:underline">
                <p className="text-sm font-medium">{meeting.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">{new Date(meeting.date).toLocaleDateString()} · {meeting.duration_minutes} min</p>
                {meeting.summary && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{meeting.summary}</p>}
              </Link>
            </div>
          ))}
        </CardContent>
      </Card>
      <DeleteConfirmationDialog
        open={deleteOpen}
        onOpenChange={(open) => !deleting && setDeleteOpen(open)}
        title={`Delete “${project.name}”?`}
        description="This project will move to the Recycle Bin. Its meetings and extracted records stay intact, and their project links return if you restore it."
        confirmLabel="Move to Recycle Bin"
        busy={deleting}
        onConfirm={deleteProject}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ListChecks className="h-4 w-4 text-primary" />
            Tasks ({project.tasks.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {project.tasks.length === 0 && (
            <p className="text-sm text-muted-foreground">No tasks tied to this project yet.</p>
          )}
          {project.tasks.map((task, i) => (
            <div key={task.id}>
              {i > 0 && <Separator className="mb-3" />}
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm">{task.description}</p>
                  <p className="text-xs text-muted-foreground">
                    {task.owner || "Unassigned"}
                    {task.deadline && ` · due ${task.deadline}`}
                    {` · ${(STATUS_LABELS[task.status] ?? task.status)}`}
                  </p>
                </div>
                {task.priority && (
                  <Badge
                    variant={
                      task.priority === "High"
                        ? "destructive"
                        : task.priority === "Medium"
                        ? "default"
                        : "secondary"
                    }
                  >
                    {task.priority}
                  </Badge>
                )}
              </div>
              <Link
                href={`/meetings/${task.meeting_id}`}
                className="mt-1 flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <CalendarDays className="h-3 w-3" />
                {task.meeting_title} · {new Date(task.meeting_date).toLocaleDateString()}
              </Link>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Scale className="h-4 w-4 text-primary" />
            Decisions ({project.decisions.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {project.decisions.length === 0 && (
            <p className="text-sm text-muted-foreground">No decisions tied to this project yet.</p>
          )}
          {project.decisions.map((decision, i) => (
            <div key={decision.id}>
              {i > 0 && <Separator className="mb-3" />}
              <p className="text-sm font-medium">{decision.decision}</p>
              {decision.reason && (
                <p className="text-sm text-muted-foreground">{decision.reason}</p>
              )}
              {(decision.alternatives ?? []).length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Rejected: {(decision.alternatives ?? []).join(", ")}
                </p>
              )}
              {decision.conflict_note && (
                <div className="mt-2 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                  <p className="text-xs text-foreground">
                    {decision.conflict_note}
                  </p>
                </div>
              )}
              <Link
                href={`/meetings/${decision.meeting_id}`}
                className="mt-1 flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <CalendarDays className="h-3 w-3" />
                {decision.meeting_title} · {new Date(decision.meeting_date).toLocaleDateString()}
              </Link>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4 text-primary" />
            Risks ({project.risks.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {project.risks.length === 0 && (
            <p className="text-sm text-muted-foreground">No risks flagged for this project yet.</p>
          )}
          {project.risks.map((risk, i) => (
            <div key={risk.id}>
              {i > 0 && <Separator className="mb-3" />}
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm">{risk.description}</p>
                {risk.severity && (
                  <Badge
                    variant={
                      risk.severity === "High"
                        ? "destructive"
                        : risk.severity === "Medium"
                        ? "default"
                        : "secondary"
                    }
                  >
                    {risk.severity}
                  </Badge>
                )}
              </div>
              <Link
                href={`/meetings/${risk.meeting_id}`}
                className="mt-1 flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <CalendarDays className="h-3 w-3" />
                {risk.meeting_title} · {new Date(risk.meeting_date).toLocaleDateString()}
              </Link>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
