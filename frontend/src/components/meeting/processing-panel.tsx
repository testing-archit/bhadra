"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, ProcessingStatus, StageName } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, MinusCircle, RotateCcw } from "lucide-react";

const RETRYABLE: StageName[] = ["transcription", "extraction", "indexing", "diarization"];
const POLL_MS = 3000;

/** Real per-stage progress for a meeting. Polls only while something is
 * pending or running, and tells the page when processing settles so it can
 * reload the notes that just arrived. */
export function ProcessingPanel({ meetingId, onSettled }: { meetingId: string; onSettled: () => void }) {
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [retrying, setRetrying] = useState<StageName | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasActive = useRef(false);
  // The page passes a new callback each render; keeping it in a ref stops
  // every parent re-render (each keystroke) from refetching and restarting
  // the poll.
  const onSettledRef = useRef(onSettled);
  useEffect(() => {
    onSettledRef.current = onSettled;
  }, [onSettled]);

  const load = useCallback(async () => {
    try {
      const next = await api.getProcessing(meetingId);
      setStatus(next);
      if (wasActive.current && !next.active) onSettledRef.current();
      wasActive.current = next.active;
    } catch {
      // The page itself reports load failures; a missed poll is not news.
    }
  }, [meetingId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!status?.active) return;
    const handle = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(handle);
  }, [status?.active, load]);

  async function retry(stage: StageName) {
    setRetrying(stage);
    setError(null);
    try {
      await api.retryStage(meetingId, stage);
      wasActive.current = true;
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Retry failed");
    } finally {
      setRetrying(null);
    }
  }

  if (!status || !status.stages?.length) return null;
  const failed = status.stages.filter((stage) => stage.status === "failed");
  if (!status.active && failed.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-lg border px-4 py-3 ${failed.length ? "border-warning/40 bg-warning/5" : "border-primary/20 bg-accent/40"}`}
    >
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <p className="text-sm font-medium">{status.active ? "Processing this meeting" : "Some processing needs attention"}</p>
        {status.stages.map((stage) => (
          <span key={stage.stage} className="flex items-center gap-1.5 text-xs text-muted-foreground" title={stage.last_error ?? undefined}>
            {stage.status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
            {stage.status === "pending" && <CircleDashed className="h-3.5 w-3.5" />}
            {stage.status === "succeeded" && <CheckCircle2 className="h-3.5 w-3.5 text-success" />}
            {stage.status === "skipped" && <MinusCircle className="h-3.5 w-3.5" />}
            {stage.status === "failed" && <AlertTriangle className="h-3.5 w-3.5 text-warning" />}
            <span className={stage.status === "failed" ? "font-medium text-foreground" : undefined}>{stage.label}</span>
          </span>
        ))}
      </div>
      {failed.map((stage) => (
        <div key={stage.stage} className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
          <p className="text-foreground">
            <span className="font-medium">{stage.label} failed</span>
            {stage.attempts > 1 && ` after ${stage.attempts} attempts`}: {stage.last_error ?? "Unknown error"}
            {stage.stage === "extraction" && status.has_transcript && " — the transcript is still available."}
          </p>
          {RETRYABLE.includes(stage.stage) && (
            <Button size="sm" variant="outline" onClick={() => void retry(stage.stage)} disabled={retrying !== null}>
              <RotateCcw className={`h-3.5 w-3.5 ${retrying === stage.stage ? "animate-spin" : ""}`} />
              Retry {stage.label.toLowerCase()}
            </Button>
          )}
        </div>
      ))}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </div>
  );
}
