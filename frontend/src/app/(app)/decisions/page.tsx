"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, DecisionListItem, ApiError } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";
import { DecisionReviewDialog } from "@/components/record-review-dialogs";
import { VerificationBadge } from "@/components/verification-badge";
import { Search, Scale, CalendarDays, AlertTriangle, FolderKanban, Trash2, Pencil, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/page-header";

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<DecisionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [reversalsOnly, setReversalsOnly] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<DecisionListItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState<DecisionListItem | null>(null);

  useEffect(() => {
    api
      .listDecisions()
      .then(setDecisions)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load decisions"));
  }, []);

  const filtered = useMemo(() => {
    if (!decisions) return null;
    const q = query.trim().toLowerCase();
    return decisions.filter(
      (d) =>
        (!reversalsOnly || d.conflict_note) &&
        (!q || d.decision.toLowerCase().includes(q) || d.reason?.toLowerCase().includes(q) || d.project?.toLowerCase().includes(q))
    );
  }, [decisions, query, reversalsOnly]);
  const reversalCount = decisions?.filter((d) => d.conflict_note).length ?? 0;

  async function deleteDecision() {
    if (!pendingDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteDecision(pendingDelete.id);
      setDecisions((current) => current?.filter((item) => item.id !== pendingDelete.id) ?? null);
      setPendingDelete(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Decision could not be deleted");
    } finally {
      setDeleting(false);
    }
  }

  async function saveDecision(fields: { decision: string; reason: string; alternatives: string[]; participants: string[] }) {
    if (!editing) return;
    const updated = await api.updateDecision(editing.id, fields);
    setDecisions((current) => current?.map((item) => item.id === updated.id ? { ...item, ...updated } : item) ?? null);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Decisions" description="Every decision your team has made, why, and what it replaced." />

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!decisions && !error && <Skeleton className="h-64 w-full" />}

      {decisions && (
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search decisions, reasons and projects"
              className="h-9 pl-9"
            />
          </div>
          {reversalCount > 0 && (
            <Button variant={reversalsOnly ? "secondary" : "outline"} className="h-9" onClick={() => setReversalsOnly((value) => !value)} aria-pressed={reversalsOnly}>
              <RefreshCw /> Reversed ({reversalCount})
            </Button>
          )}
        </div>
      )}

      {filtered?.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
          <Scale className="h-8 w-8" />
          <p className="text-sm">
            {decisions?.length === 0 ? "No decisions captured yet." : "No decisions match your search."}
          </p>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {filtered?.map((decision) => (
          <Card key={decision.id} className={decision.conflict_note ? "ring-warning/40" : undefined}>
            <CardContent className="flex flex-col gap-2 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{decision.decision}</p><VerificationBadge verifiedAt={decision.verified_at} /></div>
                <div className="flex shrink-0 items-center gap-2">
                  {decision.project &&
                    (decision.project_id ? (
                      <Link href={`/projects/${decision.project_id}`}>
                        <Badge variant="outline" className="gap-1 hover:bg-accent">
                          <FolderKanban className="h-3 w-3" />
                          {decision.project}
                        </Badge>
                      </Link>
                    ) : (
                      <Badge variant="outline" className="gap-1">
                        <FolderKanban className="h-3 w-3" />
                        {decision.project}
                      </Badge>
                    ))}
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <CalendarDays className="h-3.5 w-3.5" />
                    {new Date(decision.meeting_date).toLocaleDateString()}
                  </span>
                  <Button type="button" variant="ghost" size="icon-sm" onClick={() => setEditing(decision)} aria-label="Review decision"><Pencil className="h-3.5 w-3.5" /></Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => setPendingDelete(decision)}
                    aria-label="Delete decision"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
              {decision.reason && (
                <p className="text-sm text-muted-foreground">{decision.reason}</p>
              )}
              {decision.alternatives.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Rejected: {decision.alternatives.join(", ")}
                </p>
              )}
              {decision.conflict_note && (
                <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                  <p className="text-xs text-foreground">
                    {decision.conflict_note}
                  </p>
                </div>
              )}
              <Link
                href={`/meetings/${decision.meeting_id}`}
                className="text-xs text-primary hover:underline"
              >
                {decision.meeting_title} →
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
      {editing && <DecisionReviewDialog open={!!editing} value={editing} onOpenChange={(open) => !open && setEditing(null)} onSave={saveDecision} />}
      <DeleteConfirmationDialog
        open={!!pendingDelete}
        onOpenChange={(open) => !open && !deleting && setPendingDelete(null)}
        title="Delete this decision?"
        description={`“${pendingDelete?.decision ?? ""}” will move to the Recycle Bin and disappear from Company Memory search. The source meeting and transcript will remain.`}
        confirmLabel="Move to Recycle Bin"
        busy={deleting}
        onConfirm={deleteDecision}
      />
    </div>
  );
}
