"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Link2, Trash2, X } from "lucide-react";
import { api, ApiError, type TaskComment, type TaskHistoryEntry, type TaskLinkItem } from "@/lib/api";
import { JiraTaskPanel } from "@/components/jira-task-button";

import { STATUS_LABELS } from "@/lib/labels";
const STATUSES = ["pending", "in_progress", "done"];
const PRIORITIES = ["High", "Medium", "Low"];
const LINK_TYPES = ["blocks", "blocked_by", "depends_on", "relates_to"];

export interface EditableTask {
  id: string;
  description: string;
  owner: string | null;
  deadline: string | null;
  due_date?: string | null;
  priority: string | null;
  status: string;
  jira_issue_key?: string | null;
  jira_status?: string | null;
  jira_error?: string | null;
}

function SubtasksSection({
  subtasks,
  onAdd,
}: {
  subtasks: EditableTask[];
  onAdd: (description: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);

  async function add() {
    if (!draft.trim()) return;
    setAdding(true);
    try {
      await onAdd(draft.trim());
      setDraft("");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="flex flex-col gap-1.5 border-t pt-3">
      <Label>Sub-tasks</Label>
      {subtasks.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {subtasks.map((sub) => (
            <div key={sub.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm">
              <Badge variant={sub.status === "done" ? "default" : "outline"} className="shrink-0">
                {STATUS_LABELS[sub.status] ?? sub.status}
              </Badge>
              <span className="truncate">{sub.description}</span>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a sub-task..."
          className="flex-1"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void add();
            }
          }}
        />
        <Button size="sm" variant="outline" onClick={add} disabled={adding || !draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

const EMPTY_TASK: EditableTask = {
  id: "",
  description: "",
  owner: "",
  deadline: "",
  due_date: "",
  priority: "Medium",
  status: "pending",
};

function CommentsTab({ taskId }: { taskId: string }) {
  const [comments, setComments] = useState<TaskComment[] | null>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    api.listTaskComments(taskId).then(setComments).catch(() => setComments([]));
  }, [taskId]);

  async function post() {
    if (!draft.trim()) return;
    setPosting(true);
    try {
      const comment = await api.addTaskComment(taskId, draft.trim());
      setComments((prev) => [...(prev ?? []), comment]);
      setDraft("");
    } finally {
      setPosting(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex max-h-56 flex-col gap-2.5 overflow-y-auto">
        {comments === null ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : comments.length === 0 ? (
          <p className="text-sm text-muted-foreground">No comments yet.</p>
        ) : (
          comments.map((c) => (
            <div key={c.id} className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
              <div className="mb-0.5 flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5 font-medium text-foreground">
                  {c.author}
                  {c.source === "jira" && <span className="rounded border px-1 text-[10px] font-normal text-muted-foreground">via Jira</span>}
                </span>
                <span>{new Date(c.created_at).toLocaleString()}</span>
              </div>
              <p className="whitespace-pre-wrap">{c.body}</p>
            </div>
          ))
        )}
      </div>
      <div className="flex gap-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Leave a comment..."
          rows={2}
          className="flex-1"
        />
        <Button size="sm" onClick={post} disabled={posting || !draft.trim()} className="self-end">
          Post
        </Button>
      </div>
    </div>
  );
}

function HistoryTab({ taskId }: { taskId: string }) {
  const [history, setHistory] = useState<TaskHistoryEntry[] | null>(null);

  useEffect(() => {
    api.getTaskHistory(taskId).then(setHistory).catch(() => setHistory([]));
  }, [taskId]);

  if (history === null) return <p className="text-sm text-muted-foreground">Loading...</p>;
  if (history.length === 0) return <p className="text-sm text-muted-foreground">No changes recorded yet.</p>;

  return (
    <div className="flex max-h-72 flex-col gap-2 overflow-y-auto">
      {history.map((entry) => (
        <div key={entry.id} className="border-b pb-2 text-sm last:border-b-0">
          <p>
            <span className="font-medium">{entry.changed_by}</span> changed{" "}
            <span className="font-medium">{entry.field}</span> from{" "}
            <span className="text-muted-foreground">{entry.old_value || "(empty)"}</span> to{" "}
            <span className="text-muted-foreground">{entry.new_value || "(empty)"}</span>
          </p>
          <p className="text-xs text-muted-foreground">{new Date(entry.changed_at).toLocaleString()}</p>
        </div>
      ))}
    </div>
  );
}

function LinksTab({ taskId }: { taskId: string }) {
  const [links, setLinks] = useState<TaskLinkItem[] | null>(null);
  const [linkedTaskId, setLinkedTaskId] = useState("");
  const [linkType, setLinkType] = useState("blocks");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reload() {
    api.listTaskLinks(taskId).then(setLinks).catch(() => setLinks([]));
  }

  useEffect(reload, [taskId]);

  async function addLink() {
    if (!linkedTaskId.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.createTaskLink(taskId, linkedTaskId.trim(), linkType);
      setLinkedTaskId("");
      reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create link");
    } finally {
      setSaving(false);
    }
  }

  async function removeLink(linkId: string) {
    await api.deleteTaskLink(taskId, linkId);
    reload();
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex max-h-48 flex-col gap-2 overflow-y-auto">
        {links === null ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : links.length === 0 ? (
          <p className="text-sm text-muted-foreground">No linked tasks yet.</p>
        ) : (
          links.map((link) => (
            <div key={link.id} className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
              <div className="flex items-center gap-2 overflow-hidden">
                <Link2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <Badge variant="outline" className="shrink-0">{link.link_type.replace("_", " ")}</Badge>
                <span className="truncate">{link.linked_task_description}</span>
              </div>
              <Button variant="ghost" size="icon-sm" onClick={() => void removeLink(link.id)} aria-label="Remove link">
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))
        )}
      </div>
      <div className="flex items-center gap-2">
        <Select value={linkType} onValueChange={(v) => setLinkType(v ?? "blocks")}>
          <SelectTrigger className="w-36 shrink-0">
            <SelectValue placeholder="Type">{(v: string) => v.replace("_", " ")}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {LINK_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {t.replace("_", " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          value={linkedTaskId}
          onChange={(e) => setLinkedTaskId(e.target.value)}
          placeholder="Other task's ID"
          className="flex-1"
        />
        <Button size="sm" onClick={addLink} disabled={saving || !linkedTaskId.trim()}>
          Link
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">
        Paste the task ID from its row on the Tasks page. Linking is mutual — e.g. "blocks" automatically records
        "blocked by" on the other task.
      </p>
    </div>
  );
}

export function TaskEditDialog({
  task,
  open,
  onOpenChange,
  onSave,
  subtasks,
  onAddSubtask,
  onJiraChange,
  onDelete,
}: {
  task?: EditableTask | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (fields: {
    description: string;
    owner: string;
    deadline: string;
    due_date: string;
    priority: string;
    status: string;
  }) => Promise<void>;
  subtasks?: EditableTask[];
  onAddSubtask?: (description: string) => Promise<void>;
  /** The task was sent to / unlinked from Jira from inside the dialog. */
  onJiraChange?: (fields: { jira_issue_key: string | null; jira_status: string | null; jira_error: string | null }) => void;
  /** Offer "Delete" for an existing task (the caller confirms and deletes). */
  onDelete?: () => void;
}) {
  const isCreate = !task;
  const base = task ?? EMPTY_TASK;
  const [description, setDescription] = useState(base.description);
  const [owner, setOwner] = useState(base.owner || "");
  const [deadline, setDeadline] = useState(base.deadline || "");
  const [dueDate, setDueDate] = useState(base.due_date || "");
  const [priority, setPriority] = useState(base.priority || "Medium");
  const [status, setStatus] = useState(base.status);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave({ description, owner, deadline, due_date: dueDate, priority, status });
      onOpenChange(false);
      if (isCreate) {
        setDescription("");
        setOwner("");
        setDeadline("");
        setDueDate("");
        setPriority("Medium");
        setStatus("pending");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setDescription(base.description);
          setOwner(base.owner || "");
          setDeadline(base.deadline || "");
          setDueDate(base.due_date || "");
          setPriority(base.priority || "Medium");
          setStatus(base.status);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isCreate ? "Add task" : "Edit task"}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="details" className="gap-4">
          {!isCreate && (
            <TabsList className="w-full justify-start">
              <TabsTrigger value="details">Details</TabsTrigger>
              <TabsTrigger value="comments">Comments</TabsTrigger>
              <TabsTrigger value="links">Linked tasks</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
          )}

          <TabsContent value="details" className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="task-description">Description</Label>
              <Textarea
                id="task-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="task-owner">Owner</Label>
                <Input
                  id="task-owner"
                  value={owner}
                  onChange={(e) => setOwner(e.target.value)}
                  placeholder="Unassigned"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="task-deadline">Deadline (as said)</Label>
                <Input
                  id="task-deadline"
                  value={deadline}
                  onChange={(e) => setDeadline(e.target.value)}
                  placeholder="e.g. Friday"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="task-due-date">Due date</Label>
                <Input
                  id="task-due-date"
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Priority</Label>
                <Select value={priority} onValueChange={(v) => setPriority(v ?? "Medium")}>
                  <SelectTrigger>
                    <SelectValue placeholder="Priority">{(v: string) => v}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {PRIORITIES.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>Status</Label>
              <Select value={status} onValueChange={(v) => setStatus(v ?? "pending")}>
                <SelectTrigger>
                  <SelectValue placeholder="Status">
                    {(v: string) => STATUS_LABELS[v] ?? v}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {STATUS_LABELS[s] ?? s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {!isCreate && onAddSubtask && (
              <SubtasksSection subtasks={subtasks ?? []} onAdd={onAddSubtask} />
            )}

            {!isCreate && task && (
              <JiraTaskPanel
                taskId={task.id}
                issueKey={task.jira_issue_key}
                issueStatus={task.jira_status}
                issueError={task.jira_error}
                onChange={onJiraChange}
              />
            )}
          </TabsContent>

          {!isCreate && (
            <>
              <TabsContent value="comments">
                <CommentsTab taskId={task.id} />
              </TabsContent>
              <TabsContent value="links">
                <LinksTab taskId={task.id} />
              </TabsContent>
              <TabsContent value="history">
                <HistoryTab taskId={task.id} />
              </TabsContent>
            </>
          )}
        </Tabs>

        <DialogFooter>
          {!isCreate && onDelete && (
            <Button variant="ghost" className="mr-auto text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={onDelete} disabled={saving}>
              <Trash2 /> Delete
            </Button>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving || !description.trim()}>
            {saving ? "Saving..." : isCreate ? "Add task" : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
