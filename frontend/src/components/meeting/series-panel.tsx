"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, Repeat } from "lucide-react";
import { api, type MeetingSeries, type SeriesReviewItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STATUS: Record<SeriesReviewItem["status"], { label: string; tone: string }> = {
  done: { label: "Sounded done", tone: "bg-success/15 text-foreground" },
  in_progress: { label: "In progress", tone: "bg-primary/12 text-primary" },
  blocked: { label: "Blocked", tone: "bg-warning/15 text-foreground" },
  not_mentioned: { label: "Not mentioned", tone: "bg-muted text-muted-foreground" },
};

const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

/** For recurring meetings: the other occurrences, and what happened to the
 * previous one's open tasks according to this one's transcript. */
export function SeriesPanel({ meetingId }: { meetingId: string }) {
  const [series, setSeries] = useState<MeetingSeries | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.getMeetingSeries(meetingId).then(setSeries).catch(() => setSeries(null));
  }, [meetingId]);

  if (!series || (series.occurrences.length < 2 && !series.review)) return null;

  const items = series.review?.items ?? [];
  const confirmable = items.filter((item) => item.status === "done" && item.current_status !== "done");

  async function markDone(ids: string[]) {
    setBusy(ids.length > 1 ? "all" : ids[0]);
    try {
      await Promise.all(ids.map((id) => api.updateTaskStatus(id, "done")));
      setSeries((current) =>
        current?.review
          ? { ...current, review: { ...current.review, items: current.review.items.map((item) => (ids.includes(item.task_id) ? { ...item, current_status: "done" } : item)) } }
          : current,
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card id="series">
      <CardHeader className="gap-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Repeat className="h-4 w-4 text-primary" /> Recurring meeting
        </CardTitle>
        {series.occurrences.length > 1 && (
          <div className="flex gap-1.5 overflow-x-auto pb-1" aria-label="Occurrences">
            {series.occurrences.map((occurrence) => (
              <Link
                key={occurrence.id}
                href={`/meetings/${occurrence.id}`}
                aria-current={occurrence.current ? "page" : undefined}
                className={cn(
                  "shrink-0 rounded-full border px-3 py-1 text-xs whitespace-nowrap transition-colors hover:bg-muted",
                  occurrence.current && "border-primary bg-primary/10 font-medium text-primary hover:bg-primary/10",
                )}
                title={occurrence.title}
              >
                {shortDate(occurrence.date)}
              </Link>
            ))}
          </div>
        )}
      </CardHeader>
      {series.review && (
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium">
              Since{" "}
              <Link href={`/meetings/${series.review.previous_meeting_id}`} className="text-primary hover:underline">
                {shortDate(series.review.previous_date)}
              </Link>
            </p>
            {confirmable.length > 1 && (
              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void markDone(confirmable.map((item) => item.task_id))}>
                {busy === "all" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Mark {confirmable.length} done
              </Button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No open tasks were carried over from the last one.</p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {items.map((item) => {
                const confirmed = item.current_status === "done";
                const tone = confirmed ? { label: "Done", tone: "bg-success/15 text-foreground" } : STATUS[item.status];
                return (
                  <li key={item.task_id} className="flex flex-col gap-1.5 px-3 py-2.5 sm:flex-row sm:items-start sm:gap-3">
                    <div className="min-w-0 flex-1">
                      <p className={cn("text-sm", confirmed && "text-muted-foreground line-through")}>{item.description}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {item.owner || "No owner"}
                        {item.note && `. ${item.note}`}
                      </p>
                      {item.excerpt && <p className="mt-1 border-l-2 pl-2 text-xs text-muted-foreground italic">&ldquo;{item.excerpt}&rdquo;</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", tone.tone)}>{tone.label}</span>
                      {item.status === "done" && !confirmed && (
                        <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void markDone([item.task_id])}>
                          {busy === item.task_id ? <Loader2 className="animate-spin" /> : null} Mark done
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">Checked by AI against this meeting&apos;s transcript. Nothing is closed until someone confirms it.</p>
        </CardContent>
      )}
    </Card>
  );
}
