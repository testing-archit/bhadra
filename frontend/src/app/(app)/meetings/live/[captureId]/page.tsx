"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, AudioLines, ExternalLink } from "lucide-react";
import { MeetingBoard } from "@/components/meeting/meeting-board";
import { FigJamConnection } from "@/components/meeting/figjam-connection";
import { api, type CaptureRequestItem, type LiveBoardCaption } from "@/lib/api";
import "../../../../hackathon-intelligence.css";

export default function LiveMeetingBoardPage() {
  const { captureId } = useParams<{ captureId: string }>();
  const [capture, setCapture] = useState<CaptureRequestItem | null>(null);
  const [captions, setCaptions] = useState<LiveBoardCaption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showDraft, setShowDraft] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [requests, transcript] = await Promise.all([api.listCaptureRequests(), api.getCaptureCaptions(captureId)]);
      setCapture(requests.find((request) => request.id === captureId) ?? null);
      setCaptions(transcript);
      setError(null);
    } catch {
      setError("Could not load the live meeting. Check that you have access and try again.");
    }
  }, [captureId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return <main className="signal-intelligence-page signal-live-board-page mx-auto flex w-full max-w-[96rem] flex-col gap-5 px-4 py-6 sm:px-7">
    <Link href="/meetings" className="inline-flex w-fit items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Meetings</Link>
    <header className="signal-intelligence-hero flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="flex items-center gap-2 text-sm font-medium text-primary"><AudioLines className="size-4" />{capture?.status === "capturing" ? "Live meeting" : capture?.status_label || "Meeting session"}</p>
        <h1 className="mt-1 font-heading text-2xl font-semibold tracking-tight sm:text-3xl">{capture?.title || "Meeting board"}</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Connect your shared FigJam file and ask Wilco to draw with your voice.</p>
      </div>
      {capture?.meeting_id && <Link href={`/meetings/${capture.meeting_id}?tab=board`} className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">Open finished meeting <ExternalLink className="size-4" /></Link>}
    </header>
    {error && <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{error}</p>}
    <FigJamConnection captureId={captureId} />
    <details onToggle={event => setShowDraft(event.currentTarget.open)}><summary className="cursor-pointer text-sm text-muted-foreground">Built-in meeting draft</summary>{showDraft && <div className="mt-3"><MeetingBoard captureId={captureId} /></div>}</details>
    <section id="live-captions" className="rounded-2xl border bg-card p-4 sm:p-5" aria-label="Live transcript">
      <div className="flex items-baseline justify-between gap-3"><h2 className="font-heading text-lg font-semibold">Live transcript</h2><span className="text-xs text-muted-foreground">Caption updates may take a few seconds</span></div>
      {captions.length ? <div className="mt-4 max-h-96 space-y-3 overflow-y-auto pr-2">{captions.map((caption) => <p key={caption.seq} className="grid gap-1 border-b pb-3 text-sm last:border-b-0 sm:grid-cols-[5rem_9rem_minmax(0,1fr)]">
        <span className="text-xs tabular-nums text-muted-foreground">{Math.floor(caption.start / 60)}:{String(Math.floor(caption.start % 60)).padStart(2, "0")}</span>
        <span className="font-medium">{caption.speaker}</span><span className="leading-6 text-muted-foreground">{caption.text}</span>
      </p>)}</div> : <p className="mt-4 text-sm text-muted-foreground">Wilco will show finalized captions here as the conversation begins.</p>}
    </section>
  </main>;
}
