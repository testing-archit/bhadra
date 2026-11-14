"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ProjectSummary, ApiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";
import { Search, FolderKanban, ListChecks, Scale, ShieldAlert, CalendarDays, Plus, Trash2 } from "lucide-react";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [newProject, setNewProject] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<ProjectSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function createProject() {
    if (!newProject.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject(newProject.trim());
      setProjects((current) => [...(current || []), project].sort((a, b) => a.name.localeCompare(b.name)));
      setNewProject("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Failed to create project");
    } finally {
      setCreating(false);
    }
  }

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load projects"));
  }, []);

  const filtered = useMemo(() => {
    if (!projects) return null;
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) => p.name.toLowerCase().includes(q));
  }, [projects, query]);

  async function deleteProject() {
    if (!pendingDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteProject(pendingDelete.id);
      setProjects((current) => current?.filter((project) => project.id !== pendingDelete.id) ?? null);
      setPendingDelete(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Project could not be deleted");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Projects" description="Initiatives named across your meetings, with every meeting, task, decision and risk tied to them." />

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex gap-2">
        <Input value={newProject} onChange={(event) => setNewProject(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void createProject(); }} placeholder="Create a project or initiative" />
        <Button onClick={createProject} disabled={creating || !newProject.trim()}><Plus className="h-4 w-4" /> Create</Button>
      </div>

      {!projects && !error && <Skeleton className="h-64 w-full" />}

      {projects && (
        <div className="relative">
          <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects..."
            className="pl-9"
          />
        </div>
      )}

      {filtered?.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
          <FolderKanban className="h-8 w-8" />
          <p className="text-sm">
            {projects?.length === 0
              ? "No projects identified yet — they're tagged automatically as meetings mention them by name."
              : "No projects match your search."}
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {filtered?.map((project) => (
          <Card key={project.id} className="group relative h-full transition-colors hover:bg-accent/40">
            <Link href={`/projects/${project.id}`} className="block h-full">
              <CardContent className="flex flex-col gap-3 py-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <FolderKanban className="h-4 w-4 text-primary" />
                    {project.name}
                  </p>
                  {project.department && <Badge variant="secondary">{project.department}</Badge>}
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <CalendarDays className="h-3.5 w-3.5" />
                    {project.meeting_count} meeting{project.meeting_count === 1 ? "" : "s"}
                  </span>
                  <span className="flex items-center gap-1">
                    <ListChecks className="h-3.5 w-3.5" />
                    {project.task_count} task{project.task_count === 1 ? "" : "s"}
                  </span>
                  <span className="flex items-center gap-1">
                    <Scale className="h-3.5 w-3.5" />
                    {project.decision_count} decision{project.decision_count === 1 ? "" : "s"}
                  </span>
                  <span className="flex items-center gap-1">
                    <ShieldAlert className="h-3.5 w-3.5" />
                    {project.risk_count} risk{project.risk_count === 1 ? "" : "s"}
                  </span>
                </div>
              </CardContent>
            </Link>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="absolute right-3 bottom-3 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus:opacity-100"
              onClick={() => setPendingDelete(project)}
              aria-label={`Delete ${project.name}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </Card>
        ))}
      </div>
      <DeleteConfirmationDialog
        open={!!pendingDelete}
        onOpenChange={(open) => !open && !deleting && setPendingDelete(null)}
        title={`Delete “${pendingDelete?.name ?? "project"}”?`}
        description="This project will move to the Recycle Bin. Its meetings and extracted records stay intact, and their project links return if you restore it."
        confirmLabel="Move to Recycle Bin"
        busy={deleting}
        onConfirm={deleteProject}
      />
    </div>
  );
}
