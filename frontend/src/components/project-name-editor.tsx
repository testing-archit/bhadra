"use client";

import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** A project's name with an inline rename: pencil → input, Enter saves,
 *  Escape cancels. The name is company-wide, so every meeting, task and
 *  decision tagged with the project shows the new name. */
export function ProjectNameEditor({
  projectId,
  name,
  onRenamed,
  className,
}: {
  projectId: string;
  name: string;
  onRenamed: (name: string) => void;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function cancel() {
    setDraft(name);
    setError(null);
    setEditing(false);
  }

  async function save() {
    const next = draft.trim();
    if (!next) return;
    if (next === name) return cancel();
    setSaving(true);
    setError(null);
    try {
      const project = await api.renameProject(projectId, next);
      onRenamed(project.name);
      setEditing(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Project could not be renamed");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <span className={`flex min-w-0 items-center gap-1 ${className ?? ""}`}>
        <span className="truncate">{name}</span>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => { setDraft(name); setEditing(true); }}
          aria-label={`Rename ${name}`}
          title="Rename project"
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </span>
    );
  }

  return (
    <span className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="flex items-center gap-1">
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void save();
            if (event.key === "Escape") cancel();
          }}
          maxLength={120}
          autoFocus
          aria-label="Project name"
          className="h-8"
        />
        <Button size="icon-sm" onClick={() => void save()} disabled={saving || !draft.trim()} aria-label="Save project name">
          <Check className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={cancel} disabled={saving} aria-label="Cancel rename">
          <X className="h-3.5 w-3.5" />
        </Button>
      </span>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  );
}
