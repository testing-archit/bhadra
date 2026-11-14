"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Square, Volume2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

// One voice at a time across the whole page: starting a new answer stops
// whatever was playing.
let current: { audio: HTMLAudioElement; stop: () => void } | null = null;

type State = "idle" | "loading" | "playing" | "error";

/** Reads `text` aloud with Gnani Timbre. `compact` matches the small
 * Copy / Retry actions under chat answers; the default is an outline button. */
export function SpeakButton({ text, compact = false, autoPlay = false, className }: { text: string; compact?: boolean; autoPlay?: boolean; className?: string }) {
  const [state, setState] = useState<State>("idle");
  const urlRef = useRef<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => {
    audioRef.current?.pause();
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
  }, []);

  // A different text needs new audio.
  useEffect(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }, [text]);

  // An answer to a spoken question is spoken back without another tap.
  const autoPlayed = useRef(false);
  useEffect(() => {
    if (!autoPlay || autoPlayed.current) return;
    autoPlayed.current = true;
    void play();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPlay]);

  function stop() {
    audioRef.current?.pause();
    if (audioRef.current) audioRef.current.currentTime = 0;
    setState("idle");
  }

  async function play() {
    if (state === "playing" || state === "loading") {
      stop();
      return;
    }
    current?.stop();
    setState("loading");
    try {
      if (!urlRef.current) urlRef.current = URL.createObjectURL(await api.speak(text));
      const audio = audioRef.current ?? new Audio();
      audioRef.current = audio;
      audio.src = urlRef.current;
      audio.onended = () => setState("idle");
      current = { audio, stop };
      await audio.play();
      setState("playing");
    } catch {
      setState("error");
      window.setTimeout(() => setState("idle"), 2500);
    }
  }

  const label = state === "playing" ? "Stop" : state === "loading" ? "Loading" : state === "error" ? "Couldn't play" : "Listen";
  const Icon = state === "playing" ? Square : state === "loading" ? Loader2 : Volume2;

  return (
    <button
      type="button"
      onClick={() => void play()}
      aria-label={state === "playing" ? "Stop reading aloud" : "Read aloud"}
      aria-pressed={state === "playing"}
      title="Read aloud with Gnani Timbre"
      className={cn(
        compact
          ? "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors hover:bg-muted hover:text-foreground"
          : "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-background px-2.5 text-xs font-medium transition-colors hover:bg-muted",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
        state === "playing" && "text-primary",
        state === "error" && "text-destructive",
        className,
      )}
    >
      <Icon className={cn(compact ? "h-3 w-3" : "h-3.5 w-3.5", state === "loading" && "animate-spin")} />
      {label}
    </button>
  );
}
