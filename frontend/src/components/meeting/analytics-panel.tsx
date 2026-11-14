"use client";

import { useEffect, useState } from "react";
import { api, InsightRunItem, MeetingAnalytics } from "@/lib/api";
import { formatClock } from "@/lib/media-time";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AudioLines, Gauge, History, Info, ListChecks } from "lucide-react";

import { STATUS_LABELS } from "@/lib/labels";
function duration(seconds: number | null) {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** Evidence-based numbers for one meeting: who spoke how much, what came out
 * of it, and what processing it cost. No sentiment or judgement of people. */
export function AnalyticsPanel({
  meetingId,
  refreshKey,
  onSeek,
}: {
  meetingId: string;
  refreshKey: number;
  onSeek: (ms: number) => void;
}) {
  const [analytics, setAnalytics] = useState<MeetingAnalytics | null>(null);
  const [runs, setRuns] = useState<InsightRunItem[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getMeetingAnalytics(meetingId), api.listInsightRuns(meetingId).catch(() => [])])
      .then(([nextAnalytics, nextRuns]) => {
        if (cancelled) return;
        setAnalytics(nextAnalytics);
        setRuns(nextRuns);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [meetingId, refreshKey]);

  if (failed) return <p className="text-sm text-muted-foreground">Analytics are unavailable for this meeting.</p>;
  if (!analytics) return <Skeleton className="h-48 w-full" />;
  const talk = analytics.talk_time;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><AudioLines className="h-4 w-4 text-primary" /> Participation</CardTitle>
          <p className="text-xs text-muted-foreground">
            {talk.timed ? "Share of total speaking time" : "Share of words spoken (no timestamps available)"}
          </p>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {talk.speakers.length === 0 && <p className="text-sm text-muted-foreground">No transcript yet.</p>}
          {talk.speakers.map((row) => (
            <div key={row.speaker_key || row.speaker} className="grid grid-cols-[minmax(0,140px)_1fr_auto] items-center gap-3 text-sm">
              <span className="truncate font-medium">{row.speaker}</span>
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${Math.round(row.share * 100)}%`}>
                <div className="h-full bg-primary" style={{ width: `${Math.round(row.share * 100)}%` }} />
              </div>
              <span className="text-right text-xs text-muted-foreground tabular-nums">
                {Math.round(row.share * 100)}% · {talk.timed ? duration(row.seconds) : `${row.words} words`}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><ListChecks className="h-4 w-4 text-primary" /> Outcomes</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="grid grid-cols-3 gap-3">
            <div><p className="text-xs text-muted-foreground">Tasks</p><p className="text-lg font-semibold tabular-nums">{analytics.tasks.total}</p></div>
            <div><p className="text-xs text-muted-foreground">Decisions</p><p className="text-lg font-semibold tabular-nums">{analytics.decisions}</p></div>
            <div><p className="text-xs text-muted-foreground">Risks</p><p className="text-lg font-semibold tabular-nums">{analytics.risks}</p></div>
          </div>
          {Object.keys(analytics.tasks.by_status).length > 0 && (
            <p className="text-xs text-muted-foreground">
              {Object.entries(analytics.tasks.by_status).map(([status, count]) => `${count} ${(STATUS_LABELS[status] ?? status).toLowerCase()}`).join(" · ")}
            </p>
          )}
          {analytics.topics.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-xs font-medium text-muted-foreground">Topics in order</p>
              {analytics.topics.map((topic, index) => (
                <button
                  key={`${topic.title}-${index}`}
                  type="button"
                  disabled={topic.start_ms === null}
                  onClick={() => topic.start_ms !== null && onSeek(topic.start_ms)}
                  className="flex items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-muted/60 disabled:hover:bg-transparent"
                >
                  <span className="w-12 shrink-0 font-mono text-xs text-primary">{formatClock(topic.start_ms) || "—"}</span>
                  <span className="truncate">{topic.title}</span>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Gauge className="h-4 w-4 text-primary" /> Processing & usage</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 text-sm">
          <div><p className="text-xs text-muted-foreground">Transcription requests</p><p className="font-medium tabular-nums">{analytics.usage.transcription_requests}</p></div>
          <div><p className="text-xs text-muted-foreground">AI tokens (in / out)</p><p className="font-medium tabular-nums">{analytics.usage.ai_input_tokens.toLocaleString()} / {analytics.usage.ai_output_tokens.toLocaleString()}</p></div>
          <div>
            <p className="text-xs text-muted-foreground">Estimated cost</p>
            <p className="font-medium tabular-nums">
              {analytics.usage.estimated_cost_usd === null ? <span className="text-xs font-normal text-muted-foreground">Rates not configured</span> : `$${analytics.usage.estimated_cost_usd.toFixed(4)}`}
            </p>
          </div>
          <div><p className="text-xs text-muted-foreground">Note generations</p><p className="font-medium tabular-nums">{analytics.usage.insight_runs}</p></div>
          {Object.entries(analytics.stage_seconds).filter(([, seconds]) => seconds !== null).map(([stage, seconds]) => (
            <div key={stage}><p className="text-xs capitalize text-muted-foreground">{stage} time</p><p className="font-medium tabular-nums">{duration(seconds)}</p></div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><History className="h-4 w-4 text-primary" /> How these notes were made</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          {runs.length === 0 && <p className="text-muted-foreground">No AI generation recorded for this meeting.</p>}
          {runs.slice(0, 5).map((run) => (
            <div key={run.id} className="rounded-md border px-2.5 py-1.5">
              <p className="font-medium">
                {run.status === "succeeded" ? "Generated" : "Failed"} · {new Date(run.started_at).toLocaleString()}
              </p>
              <p className="text-muted-foreground">
                {run.model} · prompt {run.prompt_version} · template {run.template} · transcript revision {run.transcript_revision}
                {run.chunk_count > 1 && ` · ${run.chunk_count} parts`}
              </p>
              {run.status === "succeeded" && (
                <p className="text-muted-foreground">
                  {run.evidence_checked} citations checked{run.evidence_rejected ? `, ${run.evidence_rejected} rejected as invalid` : ""}
                </p>
              )}
              {run.error && <p className="text-destructive">{run.error}</p>}
            </div>
          ))}
        </CardContent>
      </Card>

      {analytics.notes.length > 0 && (
        <div className="flex items-start gap-2 rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground md:col-span-2">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div className="flex flex-col gap-1">{analytics.notes.map((note) => <p key={note}>{note}</p>)}</div>
        </div>
      )}
    </div>
  );
}
