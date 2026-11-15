"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

type Source = Awaited<ReturnType<typeof api.decisionSource>>;
export function DecisionQuote({ id, label }: { id: string; label: string }) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clip, setClip] = useState<{ segment: string; url: string } | null>(null);
  const [clipLoading, setClipLoading] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  useEffect(() => () => { if (clip) URL.revokeObjectURL(clip.url); }, [clip]);
  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next) { generation.current++; setClip(null); setLoading(false); setClipLoading(false); return; }
    if (source) return;
    const token = ++generation.current;
    setLoading(true); setError(null);
    try {
      const value = await api.decisionSource(id);
      if (token === generation.current) setSource(value);
    } catch { if (token === generation.current) setError("Couldn't load the original quote. Try again."); }
    finally { if (token === generation.current) setLoading(false); }
  }
  async function play(segment: string) {
    const token = ++generation.current;
    setClipLoading(true); setClip(null); setError(null);
    try {
      const audio = await api.decisionQuoteAudio(id, segment);
      if (token === generation.current) setClip({ segment, url: URL.createObjectURL(audio) });
    } catch { if (token === generation.current) setError("Couldn't load the audio. You can still read the source line."); }
    finally { if (token === generation.current) setClipLoading(false); }
  }
  return <div className="flex flex-col gap-2">
    <Button size="sm" variant="ghost" aria-expanded={open} aria-label={`Who said that? ${label}`} onClick={() => void toggle()}>Who said that?</Button>
    {open && <div className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3">
      {loading && <p role="status" className="text-xs text-muted-foreground">Finding the original quote…</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {source?.lines.length === 0 && <p className="text-xs text-muted-foreground">No verified transcript quote is linked to this decision.</p>}
      {source?.lines.map((line) => <div key={line.segment_id} className="flex flex-col gap-2 text-sm">
        <p className="text-xs font-medium">{line.speaker}{line.start_ms !== null ? ` · ${Math.floor(line.start_ms / 60000)}:${String(Math.floor(line.start_ms / 1000) % 60).padStart(2, "0")}` : ""}</p>
        <blockquote>“{line.original_text}”</blockquote>
        {line.text !== line.original_text && <p className="text-xs text-muted-foreground">Corrected transcript: {line.text}</p>}
        {line.audio_available ? <Button size="sm" variant="outline" disabled={clipLoading} onClick={() => void play(line.segment_id)}>{clipLoading ? "Loading…" : "Hear original quote"}</Button> : <p className="text-xs text-muted-foreground">Audio unavailable; transcript only.</p>}
        {clip?.segment === line.segment_id && <audio controls autoPlay src={clip.url} aria-label={`Original quote by ${line.speaker}`} className="w-full" />}
      </div>)}
      {source && <Link className="text-xs text-primary hover:underline" href={`/meetings/${source.meeting_id}?tab=transcript`}>Open full transcript</Link>}
    </div>}
  </div>;
}
